"""Monthly gold history, auditable chart anchors and retrospective swing analysis."""
from __future__ import annotations

import calendar
import csv
from datetime import datetime, timezone
from io import StringIO
import json
import math
from pathlib import Path
import re

from .feeds import FeedError, get_bytes

REFERENCE = Path(__file__).resolve().parents[1] / 'data' / 'reference'
WB_URL = 'https://www.worldbank.org/en/research/commodity-markets'
MIRROR_URL = 'https://raw.githubusercontent.com/datasets/gold-prices/main/data/monthly.csv'
MIRROR_PAGE = 'https://github.com/datasets/gold-prices'
FIB_SOURCE = 'https://www.cmegroup.com/education/courses/technical-analysis/fibonacci-retracements-and-extensions'
RATIOS = (0.0, .236, .382, .5, .618, .786, 1.0)


def parse_monthly(text, now=None):
    now = now or datetime.now(timezone.utc)
    current_month = now.strftime('%Y-%m')
    rows = {}
    try:
        reader = csv.DictReader(StringIO(text.lstrip('\ufeff')))
        if not {'Date', 'Price'} <= set(reader.fieldnames or []):
            raise FeedError('黄金月度数据列名无效')
        for row in reader:
            month = row['Date']
            if not re.fullmatch(r'\d{4}-\d{2}', month):
                raise FeedError('黄金月度日期格式无效')
            year, number = map(int, month.split('-'))
            datetime(year, number, 1)
            if month < '1971-01':
                continue
            if month >= current_month:
                raise FeedError('月度来源包含未来或尚未结束的月份，未采用')
            value = float(row['Price'])
            if not math.isfinite(value) or value <= 0 or month in rows:
                raise FeedError('黄金月度数据有重复、空缺或无效价格')
            rows[month] = {'date': month + '-01', 'value': value}
    except (ValueError, TypeError, KeyError) as exc:
        raise FeedError('黄金月度数据解析失败') from exc
    result = [rows[k] for k in sorted(rows)]
    if len(result) < 300 or result[0]['date'] != '1971-01-01':
        raise FeedError('长期历史覆盖不足，未替换已有数据')
    for a, b in zip(result, result[1:]):
        ay, am = map(int, a['date'][:7].split('-'))
        by, bm = map(int, b['date'][:7].split('-'))
        if by * 12 + bm - ay * 12 - am != 1:
            raise FeedError('黄金月度数据有缺月，未连接缺失区间')
    return result


def history_payload(rows, **metadata):
    year, month = map(int, rows[-1]['date'][:7].split('-'))
    return {'rows': rows, 'source': 'World Bank Pink Sheet，经 datasets/gold-prices 公开镜像',
            'source_url': WB_URL, 'retrieval_url': MIRROR_URL, 'mirror_url': MIRROR_PAGE,
            'observed_at': f'{year:04d}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}',
            'frequency': '月均价', 'unit': 'USD / troy oz',
            'basis_note': '世界银行黄金月均价，名义美元/金衡盎司；不是月末收盘价，也不是今日实时报价。',
            **metadata}


def bundled_history():
    rows = parse_monthly((REFERENCE / 'gold_monthly.csv').read_text(encoding='utf-8'))
    metadata = json.loads((REFERENCE / 'gold_monthly_metadata.json').read_text(encoding='utf-8'))
    return history_payload(rows, **metadata, bundled=True)


def fetch_long_history():
    # The official workbook's host is not reachable on every deployment. This
    # public mirror preserves its monthly grain, source attribution and raw CSV.
    rows = parse_monthly(get_bytes(MIRROR_URL, deadline_seconds=22, timeout=(5, 8), max_bytes=200_000).decode('utf-8-sig'))
    return history_payload(rows, bundled=False)


def choose_history(feed):
    seed = bundled_history()
    live = (feed or {}).get('data')
    if live and live.get('rows') and live['rows'][-1]['date'] >= seed['rows'][-1]['date']:
        return live
    return seed


def valid_points(rows):
    points = {}
    for row in rows:
        try:
            date = str(row['date'])[:10]
            datetime.fromisoformat(date)
            value = float(row['value'])
            if math.isfinite(value) and value > 0:
                points[date] = {'date': date, 'value': value}
        except (KeyError, ValueError, TypeError):
            continue
    return [points[k] for k in sorted(points)]


def fibonacci(rows, start_date=None, end_date=None):
    """Two-anchor retracements and continuation multiples, never probabilities."""
    points = valid_points(rows)
    if len(points) < 2:
        raise ValueError('至少需要两个不同日期的有效价格')
    by_date = {p['date']: p for p in points}
    if start_date is None and end_date is None:
        low = min(points, key=lambda p: p['value'])
        high = max(points, key=lambda p: p['value'])
        a, b = sorted((low, high), key=lambda p: p['date'])
    else:
        a, b = by_date[str(start_date)], by_date[str(end_date)]
    if a['date'] >= b['date'] or a['value'] == b['value']:
        raise ValueError('起点 A 须早于终点 B，且两个价格不能相同')
    direction = '上涨波段' if b['value'] > a['value'] else '下跌波段'
    levels = [{'kind': '回撤', 'ratio': r, 'value': b['value'] + (a['value'] - b['value']) * r}
              for r in RATIOS]
    levels += [{'kind': '延伸', 'ratio': r, 'value': a['value'] + (b['value'] - a['value']) * r}
               for r in (1.272, 1.618)]
    latest = points[-1]
    below = [l for l in levels if 0 < l['value'] < latest['value']]
    above = [l for l in levels if l['value'] > latest['value']]
    invalid = latest['value'] < a['value'] if direction == '上涨波段' else latest['value'] > a['value']
    return {'a': a, 'b': b, 'direction': direction, 'levels': levels, 'latest': latest,
            'below': max(below, key=lambda l: l['value']) if below else None,
            'above': min(above, key=lambda l: l['value']) if above else None,
            'invalid': invalid}


def swings(rows, threshold=.2):
    """Retrospective percent-reversal swings. Last leg is explicitly unconfirmed."""
    points = valid_points(rows)
    if len(points) < 2 or not 0 < threshold < 1:
        return []
    first, extreme, direction = points[0], points[0], 0
    low = high = first
    pivots = [first]
    for p in points[1:]:
        price = p['value']
        if direction == 0:
            if price < low['value']:
                low = p
            if price > high['value']:
                high = p
            if price >= low['value'] * (1 + threshold):
                if low['date'] != pivots[-1]['date']:
                    pivots.append(low)
                direction, extreme = 1, p
            elif price <= high['value'] * (1 - threshold):
                if high['date'] != pivots[-1]['date']:
                    pivots.append(high)
                direction, extreme = -1, p
        elif direction == 1:
            if price >= extreme['value']:
                extreme = p
            elif price <= extreme['value'] * (1 - threshold):
                pivots.append(extreme)
                direction, extreme = -1, p
        else:
            if price <= extreme['value']:
                extreme = p
            elif price >= extreme['value'] * (1 + threshold):
                pivots.append(extreme)
                direction, extreme = 1, p
    # Only reversal-confirmed extremes end completed legs. The remaining prices
    # belong to the open leg, even when its current extreme preceded the last row.
    legs = [{'a': a, 'b': b, 'confirmed': True} for a, b in zip(pivots, pivots[1:]) if a['date'] < b['date']]
    if pivots[-1]['date'] < points[-1]['date']:
        legs.append({'a': pivots[-1], 'b': points[-1], 'confirmed': False})
    for leg in legs:
        leg['change'] = leg['b']['value'] / leg['a']['value'] - 1
    return legs


def event_window(rows, event_date, months=3):
    """Pre-event calendar month to event-month+n, requiring the exact months."""
    lookup = {p['date'][:7]: p for p in valid_points(rows)}
    year, month = map(int, event_date[:7].split('-'))
    index = year * 12 + month - 1
    def key(i):
        y, m = divmod(i, 12)
        return f'{y:04d}-{m + 1:02d}'
    a, b = lookup.get(key(index - 1)), lookup.get(key(index + months))
    return {'a': a, 'b': b, 'change': b['value'] / a['value'] - 1} if a and b else None


def trend_summary(rows, short=20, long=50, lookback=5):
    points=valid_points(rows)
    if len(points)<long or len(points)<=lookback:
        return None
    latest=points[-1]
    short_mean=sum(r['value'] for r in points[-short:])/short
    long_mean=sum(r['value'] for r in points[-long:])/long
    strong=latest['value']>short_mean>long_mean
    weak=latest['value']<short_mean<long_mean
    return {'label':'偏强' if strong else '偏弱' if weak else '震荡或转折',
            'change':latest['value']/points[-lookback-1]['value']-1,
            'start':points[-lookback-1]['date'],'end':latest['date'],
            'short_mean':short_mean,'long_mean':long_mean}
