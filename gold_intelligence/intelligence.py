"""Shared, source-backed facts for forecasts, important-factor alerts and Q&A."""
from datetime import datetime, timezone, time, timedelta
import math
from zoneinfo import ZoneInfo

import pandas as pd

from .rate_freshness import rate_freshness
from .yields import resolve_rates, rate_summary

TZ=ZoneInfo('Asia/Shanghai')
CHICAGO='https://www.chicagofed.org/publications/chicago-fed-letter/2021/464'
GRAM='https://www.gold.org/goldhub/tools/gold-return-attribution-model'
GROUPS={'gold':'黄金价格与趋势','dxy':'美元指数','real_yield':'10年实际收益率',
        'nominal_yield':'10年名义收益率替代','vix':'VIX风险情绪','oil':'WTI原油','brent':'Brent原油','gas':'美国天然气期货','gld':'GLD价格代理'}


def completed_model_market(market,now=None):
    """Conservatively omit a session date until the regular NY 17:00 break.

    This is a daily-bar completion heuristic, not a settlement-price feed or
    a full exchange holiday calendar. Intraday quotes remain separate.
    """
    now=now or datetime.now(timezone.utc)
    if now.tzinfo is None:now=now.replace(tzinfo=timezone.utc)
    local=now.astimezone(ZoneInfo('America/New_York'))
    cutoff=local.date() if local.time()>=time(17) else local.date()-timedelta(days=1)
    return market.loc[[d.date()<=cutoff for d in market.index]].copy()


def local_stamp(value):
    if not value:return '尚未提供'
    try:
        if isinstance(value,(float,int)):
            if not math.isfinite(value):return '尚未安排'
            dt=datetime.fromtimestamp(value,timezone.utc)
        else:
            dt=datetime.fromisoformat(str(value).replace('Z','+00:00'))
            if dt.tzinfo is None:dt=dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(TZ).strftime('%Y-%m-%d %H:%M:%S')
    except (ValueError,TypeError,OverflowError):return '尚未提供'


def forecast_readiness(market, feeds, now=None):
    now=now or datetime.now(timezone.utc)
    if now.tzinfo is None:now=now.replace(tzinfo=timezone.utc)
    feed=feeds.get('market:GC=F',{})
    future=max(feed.get('next_attempt',0),feed.get('fetched_at',0)+feed.get('ttl',3600))
    next_check=local_stamp(future) if future>now.timestamp() else '等待下一轮后台调度'
    schedule='正在后台检查行情' if feed.get('running') else f'下次行情检查：{next_check} 北京时间' if future>now.timestamp() else '下次行情检查：等待后台调度'
    if not math.isfinite(future):schedule='当前未安排自动检查'
    result={'ready':False,'state':'waiting','message':'等待足够的期货日线，数据就绪后自动生成。',
            'schedule':schedule,'next_check':next_check,'reference_date':None,'reference':None}
    if 'Gold' not in market or not len(market['Gold'].dropna()):return result
    series=market['Gold'].dropna()
    series=series[(series>0)&series.map(math.isfinite)]
    if not len(series):return result
    reference_date=str(series.index[-1].date())
    result.update(reference_date=reference_date,reference=float(series.iloc[-1]))
    if len(series)<90:
        return {**result,'state':'insufficient','message':f'现有 {len(series)} 条有效日线，至少需要90条；历史补齐后自动生成。'}
    age=(now.astimezone(TZ).date()-series.index[-1].date()).days
    if age<0:
        return {**result,'state':'future','message':'行情日期在未来，暂停预测并等待来源修正。'}
    if age>7:
        return {**result,'state':'old','message':f'期货日线基准为 {reference_date}，超过7天未更新，暂停生成预测。'}
    return {**result,'ready':True,'state':'ready','message':'数据已就绪，统计情景预测现在可查看。'}


def model_groups(forecast):
    result=[]
    for feature in (forecast or {}).get('feature_columns',[]):
        prefix=next((g for g in GROUPS if feature.startswith(g+'_')),None)
        if prefix and GROUPS[prefix] not in result:result.append(GROUPS[prefix])
    return result


def market_factor(market,feeds,column,key,label,priority,threshold,now=None):
    now=now or datetime.now(timezone.utc)
    source=(feeds.get(key,{}) or {}).get('data') or {}
    result={'id':column,'name':label,'priority':priority,'available':False,'timely':False,
            'signal':0,'effect':'待判断','value':'暂无','change':'缺少有效历史','date':'暂无',
            'source':source.get('source','Yahoo Finance'),'url':'https://finance.yahoo.com/',
            'explanation':'缺少数据时不把影响方向填成中性。','verify':'等待数据后再判断。'}
    if column not in market:return result
    s=market[column].dropna()
    s=s[(s>0)&s.map(math.isfinite)]
    if not len(s):return result
    date=str(s.index[-1].date())
    feed=feeds.get(key,{})
    timely=0<=(now.astimezone(TZ).date()-s.index[-1].date()).days<=7 and not feed.get('error') and not feed.get('stale')
    result.update(available=True,date=date,value=f'{s.iloc[-1]:.2f}',timely=timely,
                  source=source.get('source','Yahoo Finance'),verification='日度参考' if timely else '更新或时效待核验')
    if len(s)<6:return {**result,'change':'不足6个观测值，暂无5期变化'}
    change=float(s.iloc[-1]/s.iloc[-6]-1)*100
    result.update(change=f"5个观测日 {change:+.2f}%",start=str(s.index[-6].date()),raw_change=change)
    if column=='DXY':
        signal=-1 if change>threshold else 1 if change < -threshold else 0
        result.update(signal=signal,effect='偏多假设' if signal>0 else '偏空假设' if signal<0 else '变化较小',
            explanation='美元走弱可能减轻美元计价黄金的购买成本压力，走强可能产生相反影响。',
            verify='需与实际收益率和黄金自身价格交叉验证。',url=GRAM)
    elif column=='VIX':
        signal=1 if change>threshold else -1 if change < -threshold else 0
        result.update(signal=signal,effect='避险需求可能增强' if signal>0 else '避险需求可能减弱' if signal<0 else '变化较小',
            explanation='VIX是美国股票波动率指标，不能直接等同黄金买盘；现金紧张时黄金也可能被卖出。',
            verify='核对黄金、美元及利率反应，不能只凭恐慌指数判断。',url=CHICAGO)
    elif column=='WTI':
        result.update(effect='方向有条件',explanation='原油会同时影响通胀、增长与政策预期，不能固定映射成黄金涨跌。',
                      verify='看通胀预期是否转化为更高的实际利率。',url=CHICAGO)
    return result


def important_factors(market,feeds,now=None):
    now=now or datetime.now(timezone.utc)
    rates=resolve_rates(feeds)
    info=rate_summary(rates.get('DFII10',[]))
    freshness=rate_freshness(rates.get('DFII10',[]),feeds,'DFII10',now)
    real={'id':'DFII10','name':'10年期实际收益率','priority':1,'available':bool(info),'timely':freshness['state']=='current',
          'signal':0,'effect':'待判断','value':'暂无','date':'暂无','change':'缺少有效历史',
          'source':'美国财政部 / FRED','url':'https://fred.stlouisfed.org/series/DFII10',
          'verification':freshness['label'],'explanation':'实际收益率变化影响持有无息黄金的机会成本。',
          'verify':'实际收益率下降可能支持黄金，上升可能施压；美元和需求可以抵消这一作用。'}
    if info:
        change=info.get('change5_bp')
        periods='5个有效观测值'
        start=rates['DFII10'][-6]['date'] if len(rates['DFII10'])>=6 else info.get('previous_date')
        if change is None:change,periods=info.get('change_bp'),'上一个有效观测日'
        signal=-1 if change is not None and change>5 else 1 if change is not None and change < -5 else 0
        real.update(value=f"{info['value']:.2f}%",date=info['date'],source=info.get('source','美国财政部 / FRED'),
                    change=f'{periods} {change:+.1f} 基点' if change is not None else '只有一个有效观测值',
                    raw_change=change,start=start,signal=signal,
                    effect='偏多假设' if signal>0 else '偏空假设' if signal<0 else '变化较小' if change is not None else '待判断')
    return [real,market_factor(market,feeds,'DXY','market:DX-Y.NYB','美元指数 DXY',1,.25,now),
            market_factor(market,feeds,'VIX','market:^VIX','风险情绪 VIX',2,8,now),
            market_factor(market,feeds,'WTI','market:CL=F','原油与通胀传导',2,0,now)]


def factor_conclusion(factors):
    main=factors[:2]
    if any(not f['available'] for f in main):
        return {'label':'关键因子尚未齐全','text':'实际利率或美元缺少数据，暂不形成综合方向判断。','kind':'unknown'}
    if any(not f['timely'] for f in main):
        return {'label':'先核对数据时效','text':'关键因子的最近更新尚未核验，已有变化只能作为历史参考。','kind':'unknown'}
    if all(f['signal']<0 for f in main):
        return {'label':'重点提醒：利率与美元同时形成压力假设','text':'两项5期变化均达到提醒阈值，黄金可能承压；仍须看价格与其他需求是否抵消。','kind':'bearish'}
    if all(f['signal']>0 for f in main):
        return {'label':'重点提醒：利率与美元同时形成支持假设','text':'两项5期变化均达到提醒阈值，黄金可能获得支持；仍须看后续价格是否验证。','kind':'bullish'}
    return {'label':'关键因子存在分歧或变化较小','text':'不把方向不一致或未达到阈值的变化合成确定的涨跌结论。','kind':'mixed'}
