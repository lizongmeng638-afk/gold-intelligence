"""Domestic CNY/gram history and comparable public retail quotes."""
from datetime import datetime, timedelta
from html.parser import HTMLParser
import math
from zoneinfo import ZoneInfo

from .feeds import FeedError, get_bytes, valid_time

TZ = ZoneInfo('Asia/Shanghai')
SGE_URL = 'https://www.sge.com.cn/sjzx/quotation_daily_new'
SMM_URL = 'https://precious.smm.cn/gold-price'
LOW, HIGH, MID = '#00E5A8', '#FF3B6B', '#F5C84C'
BANKS = ['建设银行', '工商银行', '农业银行', '中国银行', '招商银行', '交通银行']


class TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows, self.row, self.cell = [], None, None

    def handle_starttag(self, tag, attrs):
        if tag == 'tr':
            self.row = []
        if tag in ('td', 'th') and self.row is not None:
            self.cell = []

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in ('td', 'th') and self.cell is not None:
            self.row.append(' '.join(''.join(self.cell).split()))
            self.cell = None
        if tag == 'tr' and self.row is not None:
            self.rows.append(self.row)
            self.row = None


def table_rows(html):
    parser = TableParser()
    parser.feed(html)
    return parser.rows


def positive(value):
    number = float(str(value).replace(',', '').strip())
    if not math.isfinite(number) or number <= 0:
        raise ValueError('无效报价')
    return number


def parse_sge(html):
    found = {}
    for cells in table_rows(html):
        if len(cells) < 6 or cells[1] != 'Au99.99':
            continue
        try:
            date = datetime.strptime(cells[0], '%Y-%m-%d').date().isoformat()
            valid_time(date)
            value = positive(cells[5])
        except (ValueError, FeedError):
            continue
        found[date] = {'date': date, 'value': value}
    if not found:
        raise FeedError('上金所未返回有效 Au99.99 日线；未用国际换算价替代')
    rows = [found[k] for k in sorted(found)]
    return {'rows': rows, 'observed_at': rows[-1]['date'], 'unit': '人民币元/克',
            'source': '上海黄金交易所 · Au99.99 日收盘价', 'url': SGE_URL}


def fetch_sge():
    today = datetime.now(TZ).date()
    params = {'start_date': str(today-timedelta(days=29)), 'end_date': str(today), 'inst_ids': 'Au99.99'}
    return parse_sge(get_bytes(SGE_URL, params, timeout=(8, 8), deadline_seconds=20).decode('utf-8-sig'))


def product_group(product):
    if any(word in product.lower() for word in ['铂', '银', '18k', 'pt', '3d', '5g', '古法']):
        return None
    if any(word in product for word in ['回收', '回购']):
        return '回收参考价', '成色未注明'
    if '换' in product:
        return '换新/换购价', '成色未注明'
    if '基础' in product:
        return '投资基础价（非成品售价）', '成色未注明'
    if any(word in product for word in ['工艺', '饰品金条']):
        return '工艺金/饰品金条', '成色未注明'
    if any(word in product for word in ['投资', '金条']):
        return '投资黄金/金条', '成色未注明'
    if '9999' in product or '999.' in product:
        return '品牌金饰', '9999及以上（按原产品名核实）'
    if '999' in product:
        return '品牌金饰', '999足金'
    if any(word in product for word in ['黄金', '足金', '首饰金']):
        return '品牌金饰', '成色未注明'
    return None


def parse_retail(html):
    found = {}
    for cells in table_rows(html):
        if len(cells) != 4:
            continue
        brand, product, raw, date = cells
        group = product_group(product)
        if not group or not brand:
            continue
        try:
            date = datetime.strptime(date, '%Y-%m-%d').date().isoformat()
            valid_time(date)
            price = positive(raw)
        except (ValueError, FeedError):
            continue
        category, purity = group
        found[(brand, product, date)] = {'channel': brand, 'product': product, 'category': category,
            'purity': purity, 'side': '卖出' if category=='回收参考价' else '买入',
            'price': price, 'date': date, 'source': 'SMM公开挂牌汇总（非品牌官方接口）',
            'source_kind': '公开挂牌', 'url': SMM_URL, 'fees': '工费/手续费及门店优惠另核'}
    rows = list(found.values())
    if not rows:
        raise FeedError('品牌比价页面未返回有效黄金表格')
    return {'quotes': rows, 'observed_at': max(r['date'] for r in rows),
            'source': '上海有色网 SMM · 金店挂牌价格', 'url': SMM_URL}


def fetch_retail():
    return parse_retail(get_bytes(SMM_URL, timeout=(8, 8), deadline_seconds=20).decode('utf-8-sig'))


def comparable(rows, category, purity, date, side=None, source_kind='公开挂牌'):
    selected = [dict(r) for r in rows if r['category']==category and r['purity']==purity
                and r['date']==date and r.get('source_kind')==source_kind and (side is None or r['side']==side)]
    if source_kind == '手动录入' and selected:
        # Bank quotes should also share a 15-minute time window.
        latest = max(datetime.fromisoformat(r['quoted_at']) for r in selected)
        selected = [r for r in selected if (latest-datetime.fromisoformat(r['quoted_at'])).total_seconds() <= 900]
    selected.sort(key=lambda r:(r['price'], r['channel'], r['product']))
    if not selected:
        return []
    low, high = selected[0]['price'], selected[-1]['price']
    for row in selected:
        row['difference'] = row['price'] - low
        if len(selected)<2:
            row.update(marker='仅一条报价', color=MID)
        elif low==high:
            row.update(marker='同价', color=MID)
        elif math.isclose(row['price'], low, abs_tol=.00001):
            row.update(marker='最低价', color=LOW)
        elif math.isclose(row['price'], high, abs_tol=.00001):
            row.update(marker='最高价', color=HIGH)
        else:
            row.update(marker='中间价', color=MID)
    return selected
