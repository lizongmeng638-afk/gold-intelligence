"""Thread-safe, persistent stale-while-revalidate collection service."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import partial
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import time
from typing import Callable

from .domestic import fetch_sge, fetch_retail
from .yields import fetch_h15, fetch_rate, fetch_treasury, merge_rate_payload
from .history import fetch_long_history
from .feeds import MARKETS, FeedError, fetch_fred, fetch_gdelt, fetch_market, fetch_quote, fetch_rss, parse_time


@dataclass(frozen=True)
class FeedSpec:
    key: str
    label: str
    ttl: float
    loader: Callable
    host: str = ''
    max_observation_age: float = 0


def default_specs():
    # Submit the most useful and fastest modules first. One slow source cannot
    # prevent other results from becoming visible.
    return [
        FeedSpec('cn:history', '国内黄金 Au99.99 日线', 3600, fetch_sge, 'sge', 5*86400),
        FeedSpec('cn:retail', '国内品牌渠道挂牌价', 1800, fetch_retail, 'smm', 3*86400),
        FeedSpec('quote', '黄金现货参考报价', 60, fetch_quote, 'gold-api', 15 * 60),
        FeedSpec('history:gold', '1971年至今黄金月均价', 86400, fetch_long_history, 'github-history', 65*86400),
        FeedSpec('market:GC=F', MARKETS['GC=F'], 3600, partial(fetch_market, 'GC=F'), 'yahoo', 5 * 86400),
        FeedSpec('rates:treasury_real', '财政部10年实际收益率直连', 900, partial(fetch_treasury,'real'), 'treasury', 5*86400),
        FeedSpec('rates:treasury_nominal', '财政部2年/10年名义收益率直连', 900, partial(fetch_treasury,'nominal'), 'treasury', 5*86400),
        FeedSpec('rates:h15', '美联储H.15关键收益率', 900, fetch_h15, 'fed', 7*86400),
        FeedSpec('rates:DFII10', 'FRED 10年期实际收益率', 900, partial(fetch_rate,'DFII10'), 'fred', 7*86400),
        FeedSpec('rates:DGS2', 'FRED 2年期名义收益率', 900, partial(fetch_rate,'DGS2'), 'fred', 7*86400),
        FeedSpec('macro', 'FRED 九项宏观指标', 6 * 3600, fetch_fred, 'fred'),
        FeedSpec('news:fed', '美联储官方公告', 1800, partial(fetch_rss, 'https://www.federalreserve.gov/feeds/press_all.xml', '美联储官方 RSS'), 'fed'),
        FeedSpec('news:bls', '美国劳工统计局公告', 3600, partial(fetch_rss, 'https://www.bls.gov/feed/bls_latest.rss', '美国劳工统计局 RSS'), 'bls'),
        FeedSpec('news:bbc', 'BBC 国际新闻', 900, partial(fetch_rss, 'https://feeds.bbci.co.uk/news/world/rss.xml', 'BBC World RSS'), 'bbc'),
        *[FeedSpec(f'market:{ticker}', label, 3600, partial(fetch_market, ticker), 'yahoo', 5 * 86400)
          for ticker, label in MARKETS.items() if ticker != 'GC=F'],
        FeedSpec('news:gdelt', 'GDELT 国际新闻', 900, fetch_gdelt, 'gdelt'),
    ]


class DataHub:
    def __init__(self, cache_dir, specs=None, workers=10, clock=time.time):
        self.cache_dir = Path(cache_dir)
        self.specs = {s.key: s for s in (default_specs() if specs is None else specs)}
        self._clock = clock
        self._lock = threading.RLock()
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix='gold-feed')
        self._limits = {host: threading.BoundedSemaphore(3) for host in {s.host for s in self.specs.values()}}
        self._entries = {}
        self._revision = 0
        self._closed = False
        self.storage_error = ''
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.storage_error = f'无法创建缓存目录：{type(exc).__name__}'
        for key in self.specs:
            self._entries[key] = self._load(key)

    def _path(self, key):
        return self.cache_dir / (hashlib.sha256(key.encode()).hexdigest()[:24] + '.json')

    def _load(self, key):
        entry = {'data': None, 'fetched_at': 0.0, 'attempt_at': 0.0, 'next_attempt': 0.0,
                 'failures': 0, 'error': '', 'duration': None, 'running': False, 'from_disk': False, 'checked_at':0.0}
        path = self._path(key)
        if not path.exists():
            return entry
        try:
            raw = json.loads(path.read_text(encoding='utf-8'))
            if raw['version'] != 1 or raw['key'] != key or not isinstance(raw['data'], dict):
                raise ValueError('cache schema')
            fetched = float(raw['fetched_at'])
            if fetched > self._clock() + 600 or fetched <= 0:
                raise ValueError('cache timestamp')
            entry.update(data=raw['data'], fetched_at=fetched, next_attempt=fetched + self.specs[key].ttl,
                         from_disk=True)
        except (OSError, ValueError, TypeError, KeyError):
            entry['error'] = '本地缓存损坏，正在重新采集'
        return entry

    def _save(self, key, data, fetched):
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.cache_dir, suffix='.tmp', delete=False) as tmp:
                tmp_path = Path(tmp.name)
                json.dump({'version': 1, 'key': key, 'data': data, 'fetched_at': fetched}, tmp, ensure_ascii=False, allow_nan=False)
            tmp_path.replace(self._path(key))
        except (OSError, ValueError, TypeError) as exc:
            with self._lock:
                self.storage_error = f'缓存写入失败：{type(exc).__name__}；当前会话仍可使用内存数据'
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)

    def refresh_due(self, force=False, quote_interval=60):
        """Return immediately. Force never erases data, duplicates jobs or bypasses backoff."""
        scheduled = 0
        now = self._clock()
        with self._lock:
            if self._closed:
                return 0
            for key, spec in self.specs.items():
                e = self._entries[key]
                ttl = max(spec.ttl, quote_interval) if key == 'quote' else spec.ttl
                if e['running']:
                    continue
                if e['failures'] and now < e['next_attempt']:
                    continue
                if force:
                    if e['attempt_at'] and now - e['attempt_at'] < 30:
                        continue
                elif now < max(e['next_attempt'], e['fetched_at'] + ttl):
                    continue
                e.update(running=True, attempt_at=now)
                self._revision += 1
                self._pool.submit(self._collect, spec)
                scheduled += 1
        return scheduled

    def _collect(self, spec):
        start = time.monotonic()
        try:
            with self._limits[spec.host]:
                data = spec.loader()
            if not isinstance(data, dict):
                raise FeedError('数据格式无效')
            fetched = self._clock()
            with self._lock:
                e = self._entries[spec.key]
                if spec.key == 'history:gold' and e['data'] and data.get('observed_at','') < e['data'].get('observed_at',''):
                    raise FeedError('黄金月度来源返回较早月份，保留较新历史数据')
                if spec.key.startswith('rates:'):
                    data = merge_rate_payload(e['data'],data,e['fetched_at'],fetched)
                # A partial macro response must not delete successful older series.
                if spec.key == 'macro' and e['data']:
                    previous = e['data']
                    data = {**data,
                            'series': {**previous.get('series', {}), **data.get('series', {})},
                            'series_fetched': {**previous.get('series_fetched', {}), **data.get('series_fetched', {})}}
                e.update(data=data, fetched_at=fetched, next_attempt=fetched + spec.ttl,
                         failures=0, error='', from_disk=False)
            self._save(spec.key, data, fetched)
        except Exception as exc:
            with self._lock:
                e = self._entries[spec.key]
                failures = e['failures'] + 1
                delay = max(min(900, 30 * (2 ** min(failures - 1, 5))), getattr(exc, 'retry_after', 0))
                message = str(exc) if isinstance(exc, FeedError) else f'{type(exc).__name__}：{str(exc)[:160]}'
                e.update(failures=failures, error=message, next_attempt=self._clock() + delay)
        finally:
            with self._lock:
                self._entries[spec.key].update(running=False, checked_at=self._clock(), duration=round(time.monotonic() - start, 3))
                self._revision += 1

    def snapshot(self):
        now = self._clock()
        with self._lock:
            out = {}
            for key, e in self._entries.items():
                spec = self.specs[key]
                data = e['data']
                age = max(0, now - e['fetched_at']) if data is not None else None
                stale = data is not None and age >= spec.ttl
                observation_old = False
                if data and data.get('observed_at') and spec.max_observation_age:
                    try:
                        observation_old = now - parse_time(data['observed_at']).timestamp() > spec.max_observation_age
                    except (ValueError, TypeError):
                        observation_old = True
                status = ('更新中（保留缓存）' if data is not None else '首次采集中') if e['running'] else (
                    ('更新失败，使用缓存' if data is not None else '暂不可用') if e['error'] else (
                    '来源返回较旧数据，保留较新缓存' if data and data.get('source_regressed') else (
                    '部分指标未更新' if data and data.get('missing') else (
                    '来源数据较旧' if observation_old else ('缓存待更新' if stale else ('本地缓存' if e['from_disk'] else '已取得'))))))
                out[key] = {**e, 'label': spec.label, 'ttl': spec.ttl, 'age': age, 'stale': stale,
                            'observation_old': observation_old, 'status': status,
                            'retry_in': max(0, int(e['next_attempt'] - now)) if e['error'] else 0}
            return {'revision': self._revision, 'feeds': out, 'storage_error': self.storage_error}

    def close(self):
        with self._lock:
            self._closed = True
        self._pool.shutdown(wait=True)
