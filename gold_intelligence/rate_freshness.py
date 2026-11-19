"""Conservative daily-rate freshness: publication calendar != download clock."""
from datetime import datetime,time,timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

import pandas as pd
from pandas.tseries.holiday import USFederalHolidayCalendar,GoodFriday

from .feeds import UTC,parse_time
from .yields import RATE_KEYS,RATE_SUPPORT,clean_rows,rate_summary

NY=ZoneInfo('America/New_York')
CHECK_TTL=900


@lru_cache(maxsize=12)
def closed_days(year):
    start=f'{year-1}-12-01';end=f'{year+1}-01-31'
    holidays=USFederalHolidayCalendar().holidays(start=start,end=end)
    friday=GoodFriday.dates(start_date=pd.Timestamp(start),end_date=pd.Timestamp(end))
    return {d.date() for d in list(holidays)+list(friday)}


def expected_observation_date(now=None):
    now=now or datetime.now(UTC)
    if now.tzinfo is None:
        now=now.replace(tzinfo=UTC)
    local=now.astimezone(NY)
    # 17:00 NY is a conservative checking benchmark, not a promised release time.
    date=local.date() if local.time()>=time(17) else local.date()-timedelta(days=1)
    holidays=closed_days(local.year)
    while date.weekday()>=5 or date in holidays:
        date-=timedelta(days=1)
    return date


def completed_check(entry):
    data=entry.get('data') or {}
    return entry.get('checked_at') or data.get('latest_check_at') or entry.get('fetched_at') or 0


def reported_date(data,sid):
    if 'checked_latest_dates' in data:
        return data['checked_latest_dates'].get(sid)
    rows=clean_rows(data.get('series',{}).get(sid,[]))
    return rows[-1]['date'] if rows else None


def rate_freshness(rows,feeds,sid,now=None):
    now=now or datetime.now(UTC)
    if now.tzinfo is None:
        now=now.replace(tzinfo=UTC)
    info=rate_summary(rows)
    expected=str(expected_observation_date(now))
    if info is None:
        return {'state':'missing','label':'暂无有效数据','color':'#FFB84D','is_delayed':None,'expected_date':expected,'last_checked_at':0,'known_latest_date':None}
    candidates=[]
    verified=False;running=False;failed=False;regressed=False
    for key in RATE_KEYS:
        if sid not in RATE_SUPPORT.get(key,()):
            continue
        entry=feeds.get(key,{})
        data=entry.get('data') or {}
        checked=completed_check(entry)
        date=reported_date(data,sid)
        fresh=checked>0 and 0<=now.timestamp()-checked<=min(entry.get('ttl',CHECK_TTL),CHECK_TTL)
        candidates.append((checked,date))
        verified |= bool(fresh and not entry.get('error') and date and date>=info['date'])
        running |= bool(entry.get('running'))
        failed |= bool(fresh and entry.get('error'))
        regressed |= bool(fresh and sid in data.get('source_regressed',[]))
    latest=max([date for _,date in candidates if date]+[info['date']])
    checked=max((t for t,_ in candidates),default=0)
    if info['date']<latest:
        state,label,color,delayed='behind','已延迟：落后已取得的官方观测','#FF4F76',True
    elif info['date']<expected:
        state,label,color,delayed='possibly_delayed',f'可能延迟：按发布日估计应到 {expected}','#FFB84D',None
    elif verified:
        state,label,color,delayed='current','未见延迟 · 已核验官方日度数据','#00E5A8',False
    elif regressed:
        state,label,color,delayed='regressed','来源返回较旧数据，已保留较新缓存','#FFB84D',None
    elif running:
        state,label,color,delayed='checking','正在核验 · 当前为已有缓存','#FFB84D',None
    elif failed:
        state,label,color,delayed='failed','检查失败 · 缓存是否最新待核验','#FFB84D',None
    else:
        state,label,color,delayed='unverified','检查已过期或尚未核验最新','#FFB84D',None
    return {'state':state,'label':label,'color':color,'is_delayed':delayed,'expected_date':expected,
            'last_checked_at':checked,'known_latest_date':latest,
            'data_fetched_at':info.get('fetched_at'),
            'source_updated_at':info.get('source_updated_at'),
            'source_release_date':info.get('source_release_date')}
