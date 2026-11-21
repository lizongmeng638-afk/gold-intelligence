"""Public feeds. No Streamlit calls or network work on the rendering thread."""
from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from io import BytesIO, StringIO
import math
import re
import time
import tempfile
import threading
from pathlib import Path
from urllib.parse import quote, urlparse
from xml.etree import ElementTree
from zipfile import ZipFile

import requests

_YF_SETUP_LOCK = threading.Lock()
_YF_CONFIGURED = False

UTC = timezone.utc
FRED_IDS = ('DFII10', 'DGS2', 'DGS10', 'T10YIE', 'CPIAUCSL', 'PCEPI', 'UNRATE', 'FEDFUNDS', 'PAYEMS')
MARKETS = {'GC=F': 'COMEX黄金期货', 'DX-Y.NYB': '美元指数 DXY', '^TNX': '10年期名义收益率',
           '^VIX': 'VIX', 'CL=F': 'WTI原油', 'BZ=F':'Brent原油','NG=F':'美国天然气期货', 'GLD': 'GLD价格', 'CNY=X': 'USD/CNY'}
HEADERS = {'User-Agent': 'GOLD-INTELLIGENCE/1.1 (local public-data research)',
           'Accept': 'application/json,text/csv,application/xml,text/xml,*/*'}


class FeedError(RuntimeError):
    def __init__(self, message, retry_after=0):
        super().__init__(message)
        self.retry_after = retry_after


def iso_now():
    return datetime.now(UTC).isoformat()


def parse_time(value):
    if not value:
        raise ValueError('缺少数据时间')
    value = str(value)
    if re.fullmatch(r'\d{8}T\d{6}Z', value):
        return datetime.strptime(value, '%Y%m%dT%H%M%SZ').replace(tzinfo=UTC)
    if re.fullmatch(r'\d{14}', value):
        return datetime.strptime(value, '%Y%m%d%H%M%S').replace(tzinfo=UTC)
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        dt = parsedate_to_datetime(value)
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def valid_time(value):
    dt = parse_time(value)
    if dt > datetime.now(UTC) + timedelta(minutes=10):
        raise FeedError('来源返回未来时间，未采用')
    return dt.isoformat()


def safe_url(value):
    value = str(value or '').strip()
    parts = urlparse(value)
    return value if parts.scheme in ('https', 'http') and parts.netloc else ''


def get_bytes(url, params=None, deadline_seconds=12, max_bytes=3_000_000, timeout=(3, 6), request_headers=None):
    """No retries here: the hub performs bounded, per-feed backoff."""
    start = time.monotonic()
    try:
        with requests.get(url, params=params, headers={**HEADERS, **(request_headers or {})}, timeout=timeout, stream=True) as r:
            if r.status_code == 429:
                retry = r.headers.get('Retry-After', '120')
                try:
                    delay = float(retry)
                except ValueError:
                    try:
                        delay = (parse_time(retry) - datetime.now(UTC)).total_seconds()
                    except (ValueError, TypeError):
                        delay = 120
                raise FeedError('HTTP 429：数据源限流，已暂停重试', max(30, min(delay, 86400)))
            r.raise_for_status()
            chunks, size = [], 0
            for chunk in r.iter_content(16384):
                size += len(chunk)
                if size > max_bytes:
                    raise FeedError('返回数据超过大小限制')
                if time.monotonic() - start > deadline_seconds:
                    raise FeedError('读取超过时间预算')
                chunks.append(chunk)
            return b''.join(chunks)
    except requests.Timeout as exc:
        raise FeedError('连接或读取超时；本轮未更新') from exc
    except requests.RequestException as exc:
        status = getattr(getattr(exc, 'response', None), 'status_code', None)
        raise FeedError(f'HTTP {status}' if status else f'网络连接失败：{type(exc).__name__}') from exc


def get_json(url, params=None):
    import json
    try:
        return json.loads(get_bytes(url, params))
    except (ValueError, UnicodeError) as exc:
        raise FeedError('接口未返回有效 JSON（可能为错误页）') from exc


def fetch_quote():
    data = get_json('https://api.gold-api.com/price/XAU')
    price = float(data['price'])
    if data.get('symbol') != 'XAU' or data.get('currency', 'USD') != 'USD':
        raise FeedError('黄金报价币种或品种不符')
    if not math.isfinite(price) or price <= 0:
        raise FeedError('黄金报价数值无效')
    return {'price': price, 'observed_at': valid_time(data['updatedAt']),
            'source': 'Gold API · XAU/USD 现货参考', 'instrument': 'spot',
            'url': 'https://gold-api.com/assets/gold'}


def parse_market(data, ticker):
    chart = data.get('chart', {})
    if chart.get('error'):
        raise FeedError(str(chart['error'].get('description', 'Yahoo Finance 返回错误')))
    results = chart.get('result') or []
    if not results:
        raise FeedError('Yahoo Finance 未返回行情')
    item = results[0]
    if item.get('meta', {}).get('symbol') != ticker:
        raise FeedError('行情品种与请求不符')
    times = item.get('timestamp') or []
    closes = item.get('indicators', {}).get('quote', [{}])[0].get('close', [])
    from zoneinfo import ZoneInfo
    zone = ZoneInfo(item.get('meta', {}).get('exchangeTimezoneName', 'UTC'))
    rows = {}
    for stamp, value in zip(times, closes):
        if value is None:
            continue
        value = float(value)
        dt = datetime.fromtimestamp(stamp, UTC)
        if not math.isfinite(value) or value <= 0:
            continue
        valid_time(dt.isoformat())
        rows[dt.astimezone(zone).date().isoformat()] = {'date': dt.astimezone(zone).date().isoformat(), 'value': value}
    if not rows:
        raise FeedError('没有有效收盘价')
    rows = [rows[k] for k in sorted(rows)]
    return {'rows': rows, 'observed_at': rows[-1]['date'], 'ticker': ticker,
            'source': f'Yahoo Finance · {ticker}' + ('（COMEX期货代理，非现货）' if ticker == 'GC=F' else ''),
            'instrument': 'futures' if ticker == 'GC=F' else 'market',
            'url': f'https://finance.yahoo.com/quote/{quote(ticker, safe="")}/history/'}


def _fetch_market_yfinance(ticker):
    # The library maintains Yahoo cookies and supports its alternate chart host.
    # Configure a writable cache once; collection remains in background workers.
    global _YF_CONFIGURED
    import yfinance as yf
    with _YF_SETUP_LOCK:
        if not _YF_CONFIGURED:
            yf.set_tz_cache_location(str(Path(tempfile.gettempdir()) / 'gold-intelligence-yahoo'))
            _YF_CONFIGURED = True
    frame = yf.Ticker(ticker).history(period='5y', interval='1d', auto_adjust=True, timeout=8)
    if frame is None or frame.empty or 'Close' not in frame:
        raise FeedError('yfinance备用方式未返回历史行情')
    frame = frame.dropna(subset=['Close'])
    result = parse_market({'chart': {'result': [{
        'meta': {'symbol': ticker, 'exchangeTimezoneName': str(frame.index.tz or 'UTC')},
        'timestamp': [int(dt.timestamp()) for dt in frame.index],
        'indicators': {'quote': [{'close': [float(v) for v in frame['Close']]}]}
    }]}}, ticker)
    result['source'] += ' · yfinance备用抓取'
    return result


def fetch_market(ticker):
    # Avoid XAUUSD=X. Try the public chart once, then the supported library
    # transport once. The hub retains normal backoff and per-host concurrency.
    try:
        data = get_json(f'https://query1.finance.yahoo.com/v8/finance/chart/{quote(ticker, safe="")}',
                        {'range': '5y', 'interval': '1d'})
        return parse_market(data, ticker)
    except FeedError as primary:
        try:
            return _fetch_market_yfinance(ticker)
        except Exception as fallback:
            raise FeedError(f'{primary}；备用抓取失败：{type(fallback).__name__}: {str(fallback)[:100]}',
                            retry_after=primary.retry_after) from fallback


def parse_fred(content):
    """FRED can return plain CSV or a ZIP containing daily.csv + monthly.csv."""
    if content.startswith(b'PK'):
        with ZipFile(BytesIO(content)) as archive:
            csv_parts = []
            total = 0
            for info in archive.infolist():
                if not info.filename.lower().endswith('.csv'):
                    continue
                total += info.file_size
                if total > 10_000_000:
                    raise FeedError('宏观压缩包内容超过大小限制')
                csv_parts.append(archive.read(info))
    else:
        csv_parts = [content]
    series = {sid: {} for sid in FRED_IDS}
    cutoff = (datetime.now(UTC) - timedelta(days=365 * 6)).date().isoformat()
    for part in csv_parts:
        reader = csv.DictReader(StringIO(part.decode('utf-8-sig')))
        fields = reader.fieldnames or []
        if not fields or not any(sid in fields for sid in FRED_IDS):
            continue
        date_key = next((k for k in fields if k.lower() in ('date', 'observation_date')), fields[0])
        for row in reader:
            stamp = row.get(date_key, '')
            try:
                stamp = datetime.strptime(stamp, '%Y-%m-%d').date().isoformat()
                valid_time(stamp)
            except (ValueError, FeedError):
                continue
            if stamp < cutoff:
                continue
            for sid in FRED_IDS:
                try:
                    value = float(row.get(sid, ''))
                except (TypeError, ValueError):
                    continue
                if math.isfinite(value):
                    series[sid][stamp] = {'date': stamp, 'value': value}
    series = {sid: [values[k] for k in sorted(values)] for sid, values in series.items() if values}
    if not series:
        raise FeedError('FRED 未返回有效指标（可能为 HTML 错误页）')
    now = iso_now()
    return {'series': series, 'series_fetched': {sid: now for sid in series},
            'missing': [sid for sid in FRED_IDS if sid not in series],
            'source': 'FRED 公共 CSV（混合频率 ZIP 自动解包）',
            'observed_at': max(rows[-1]['date'] for rows in series.values()),
            'url': 'https://fred.stlouisfed.org/'}


def fetch_fred():
    return parse_fred(get_bytes('https://fred.stlouisfed.org/graph/fredgraph.csv',
                               {'id': ','.join(FRED_IDS)}, max_bytes=5_000_000, timeout=(4, 8), deadline_seconds=15))


def normalize_news(items,limit=60):
    result, titles, urls = [], set(), set()
    for item in items:
        title = re.sub(r'\s+', ' ', str(item.get('title', ''))).strip()
        url = safe_url(item.get('url'))
        token = title.casefold()
        if not title or not url or token in titles or url in urls:
            continue
        try:
            stamp = valid_time(item.get('date'))
        except (ValueError, TypeError, FeedError):
            continue
        titles.add(token)
        urls.add(url)
        result.append({**item, 'title': title, 'url': url, 'date': stamp,
                       'domain': urlparse(url).netloc})
    return sorted(result, key=lambda r: r['date'], reverse=True)[:limit]


def fetch_gdelt():
    data = get_json('https://api.gdeltproject.org/api/v2/doc/doc',
                    {'query': '(gold OR bullion OR "Federal Reserve" OR inflation OR "Treasury yields" OR tariff)',
                     'mode': 'ArtList', 'format': 'json', 'maxrecords': 40, 'sort': 'DateDesc', 'timespan': '24h'})
    if not isinstance(data.get('articles'), list):
        raise FeedError('GDELT 返回格式无效')
    items = normalize_news([{'title': a.get('title'), 'url': a.get('url'), 'date': a.get('seendate'),
                             'source': 'GDELT', 'time_kind': 'GDELT收录时间'} for a in data['articles']])
    return {'items': items, 'source': 'GDELT 国际新闻（收录时间不等于事件发生时间）',
            'observed_at': items[0]['date'] if items else None, 'url': 'https://www.gdeltproject.org/'}


def fetch_rss(url, name):
    try:
        root = ElementTree.fromstring(get_bytes(url))
    except ElementTree.ParseError as exc:
        raise FeedError('RSS 内容无效') from exc
    items = []
    for node in root.findall('.//item'):
        stamp = node.findtext('pubDate') or node.findtext('{http://purl.org/dc/elements/1.1/}date')
        description=re.sub(r'<[^>]+>',' ',node.findtext('description',''))
        items.append({'title': node.findtext('title', ''), 'url': node.findtext('link', ''),
                      'description':re.sub(r'\s+',' ',description).strip()[:800],
                      'date': stamp, 'source': name, 'time_kind': '来源发布时间'})
    items = normalize_news(items)
    if not items:
        raise FeedError('官方 RSS 无有效条目')
    return {'items': items, 'source': name, 'observed_at': items[0]['date'], 'url': url}
