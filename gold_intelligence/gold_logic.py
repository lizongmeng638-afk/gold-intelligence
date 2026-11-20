"""Curated historical evidence. Transmission paths are explicitly hypotheses."""
from pathlib import Path
import json

EVENTS = json.loads((Path(__file__).resolve().parents[1] / 'data/reference/gold_events.json').read_text(encoding='utf-8'))
BOE = 'https://www.bankofengland.co.uk/museum/online-collections/blog/as-good-as-gold'
CHICAGO = 'https://www.chicagofed.org/publications/chicago-fed-letter/2021/464'
VALUE_TEXT = '黄金的稀缺、耐久和易分割性，使它先成为饰品和财富载体，后来用于货币与储备。它本身不支付利息，今天的价格由持有成本、货币预期和买卖需求共同决定。历史地位并不保证每个买入时点都能盈利。'
HISTORY_TEXT = '早期金属货币 → 金本位下的纸币兑换 → 1944年布雷顿森林体系 → 1971年美元停止向外国官方持有者兑金 → 现代黄金市场。固定兑换比价与市场交易价并不相同；主图从1971年开始，使用可比的名义美元月均价。'
DRIVERS = [
    {'name':'实际利率：持有黄金的机会成本', 'path':'实际收益率下降 → 相对持有债券的收益差收窄 → 可能支持黄金；反向变化可能施压。', 'check':'对照10年期实际收益率、美元和金价是否同步；通胀上升也可能引发加息。', 'url':CHICAGO},
    {'name':'货币与美元：计价和购买力', 'path':'美元走弱 → 非美元投资者购买黄金的本币成本可能下降；通胀和货币信心也会影响需求。', 'check':'关注美元指数、通胀预期与政策反应；关系会随时期变化，不能固定套用。', 'url':CHICAGO},
    {'name':'风险与流动性：避险也有先后', 'path':'不确定性上升可能增加避险需求；现金紧张时，投资者也可能先卖黄金补充流动性。', 'check':'同时检查美元、实际利率和市场压力；事件标题不能单独决定价格方向。', 'url':CHICAGO},
    {'name':'实物与机构需求：谁在买、谁在卖', 'path':'央行储备调整、基金申赎、首饰与金条需求，会改变市场买卖力量；不同主体的行动可能相反。', 'check':'核对需求报告的统计期和发布日期；历史年度购金不能当作今日流入。', 'url':'https://www.gold.org/goldhub/research/gold-demand-trends/gold-demand-trends-full-year-2024/central-banks'},
]
