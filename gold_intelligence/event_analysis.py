"""News pathways and explicitly hypothetical stress ranges, not causal estimates."""
from datetime import datetime, timezone
import hashlib
import math
import re
from urllib.parse import urlparse,parse_qsl,urlencode,urlunparse

from .feeds import parse_time
from .models import classify_news


def canonical_url(url):
    u=urlparse(str(url));query=[(k,v) for k,v in parse_qsl(u.query) if not k.lower().startswith(('utm_','fbclid','gclid'))]
    return urlunparse((u.scheme.lower(),u.netloc.lower(),u.path,'',urlencode(query),''))


def message_key(item):
    return hashlib.sha256(canonical_url(item.get('url','')).encode()).hexdigest()[:24]


def analyze_message(item):
    text=(item.get('title','')+' '+item.get('description','')).lower()
    if item.get('full_text_obtained') and item.get('stance','').startswith(('偏鹰','偏鸽')):
        return {'category':'美联储正文措辞','direction':item['stance']+'，条件和时点需核对',
                'path':'官方讲话措辞 → 政策路径预期可能调整 → 核对美元与实际收益率 → 黄金重新定价',
                'counter':'个人发言不等于集体决定，已被计价的观点也未必带来新的金价变动。',
                'validation':'阅读完整语境与发言日期；不按鹰鸽条数推算加息概率。','basis':'正文规则线索，非政策承诺或因果效应'}
    if re.search(r'\b(?:ceasefire|truce|de.escalation|peace deal)\b',text):
        return {'category':'地缘缓和','direction':'避险溢价可能回落','path':'缓和消息 → 避险需求可能降低 → 观察黄金是否回落',
                'counter':'美元或实际收益率下行可能抵消避险需求减弱。','validation':'核实是否落地，观察美元、实际利率及金价反应。','basis':'标题/摘要规则，未作事件因果识别'}
    if re.search(r'\b(?:oil|crude|natural gas|energy prices?|strait|hormuz|opec|pipeline|shipping disruptions?|energy supply)\b',text):
        return {'category':'能源/供给冲击','direction':'存在双向传导','path':'能源供给受扰或价格变化 → 通胀、增长与政策预期变化 → 美元/实际利率和避险需求重新定价',
                'counter':'油价上涨可推高保值需求，也可引出更紧货币政策；油价下跌也不能直接等同利空黄金。','validation':'同时核对WTI、Brent、天然气、PPI与利率；并非每种能源同向变动。','basis':'标题/摘要规则，未估计价格影响幅度'}
    if re.search(r'\b(?:wars?|missiles?|attacks?|invasion|escalation|conflicts?|sanctions?|unrest|coup|geopolitical)\b',text):
        return {'category':'地缘风险','direction':'避险支持与流动性抛售可能并存','path':'风险升级 → 避险及现金需求变化 → 黄金可能先跌后涨，也可能不响应',
                'counter':'美元走强、实际收益率上行或杠杆平仓可能抵消避险买盘。','validation':'核实来源与发生时间，查看金价、美元、收益率和风险指标是否验证。','basis':'标题/摘要规则，不代表已核验事件全部细节'}
    category,direction,path,validation=classify_news(item)
    return {'category':category,'direction':direction,'path':path,'counter':'其他政策、美元、利率和资金需求可能抵消该传导。',
            'validation':validation,'basis':'标题/摘要规则，非全文因果结论'}


def recent_messages(news,speeches,now=None,days=7):
    now=now or datetime.now(timezone.utc);items={}
    for original in list(news)+list(speeches):
        if not original.get('date'):continue
        text=(original.get('title','')+' '+original.get('description','')).lower()
        relevant=original.get('source_key') or re.search(r'\b(?:gold|bullion|fomc|fed|federal reserve|interest rates?|monetary|inflation|ppi|pmi|cpi|pce|payrolls?|unemployment|jobless|dollar|treasury|yields?|central banks?|economy|economic|tariffs?|sanctions?|wars?|missiles?|attacks?|invasion|conflicts?|ceasefire|truce|oil|crude|energy|natural gas|opec|hormuz|recession|financial stability)\b',text)
        if not relevant:continue
        try:age=(now-parse_time(original['date'])).total_seconds()
        except (ValueError,TypeError):continue
        if age<0 or age>days*86400:continue
        item={**original,'key':message_key(original),'analysis':analyze_message(original)}
        previous=items.get(item['key'])
        if previous is None or item.get('full_text_obtained'):items[item['key']]=item
    return sorted(items.values(),key=lambda i:i['date'],reverse=True)


def stress_range(forecast,horizon,scenario,multiple):
    if not forecast:return None
    if scenario not in ('baseline','pressure','support','geopolitics','energy'):raise ValueError('unknown scenario')
    if not math.isfinite(multiple) or not 0<=multiple<=2:raise ValueError('shock outside permitted range')
    row=next(r for r in forecast['rows'] if r['h']==horizon)
    shock=float(forecast['vol'])*math.sqrt(horizon)*multiple
    lower=row['low80']*math.exp(-shock) if scenario in ('pressure','geopolitics','energy') else row['low80']
    upper=row['high80']*math.exp(shock) if scenario in ('support','geopolitics','energy') else row['high80']
    return {'low':lower,'high':upper,'shock':shock,'multiple':multiple,'scenario':scenario,'h':horizon,
            'baseline_low':row['low80'],'baseline_high':row['high80'],
            'classification':'用户假设的压力边界，无统计覆盖率；不是新闻自动预测或交易建议'}
