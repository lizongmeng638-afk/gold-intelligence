"""Independent daily Treasury constant-maturity rates and change calculations."""
from datetime import datetime, timedelta
from io import StringIO
import csv
import math
import re
from xml.etree import ElementTree

from .domestic import table_rows
from .feeds import FeedError, UTC, get_bytes, parse_time, valid_time

TREASURY_URL = 'https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml'
RATE_KEYS = ['macro','rates:h15','rates:DFII10','rates:DGS2','rates:treasury_real','rates:treasury_nominal']
RATE_SUPPORT = {'macro':('DFII10','DGS2','DGS10'),'rates:h15':('DFII10','DGS2','DGS10'),
 'rates:DFII10':('DFII10',),'rates:DGS2':('DGS2',),
 'rates:treasury_real':('DFII10',),'rates:treasury_nominal':('DGS2','DGS10')}

H15_URL = 'https://www.federalreserve.gov/releases/h15/'
RATE_LABELS = {'DFII10':'10年期实际收益率（TIPS）','DGS2':'2年期美债收益率（名义）','DGS10':'10年期美债收益率（名义）'}


def clean_rows(rows):
    valid = {}
    for row in rows:
        try:
            date = datetime.strptime(str(row['date']), '%Y-%m-%d').date().isoformat()
            valid_time(date)
            value = float(row['value'])
            if not math.isfinite(value):
                continue
            valid[date] = {**row, 'date':date, 'value':value}
        except (ValueError,TypeError,KeyError,FeedError):
            continue
    return [valid[d] for d in sorted(valid)]


def parse_h15(html):
    dates, section, in_treasury = None, None, False
    series = {sid:[] for sid in RATE_LABELS}
    for row in table_rows(html):
        if not row:
            continue
        label = row[0].strip().lower()
        if label=='instruments':
            dates=[]
            for cell in row[1:]:
                token = re.sub(r'[^A-Za-z0-9]', '', cell)
                try:
                    dates.append(datetime.strptime(token,'%Y%b%d').date().isoformat())
                except ValueError:
                    dates.append(None)
            continue
        if label.startswith('treasury constant maturities'):
            in_treasury = True
            continue
        if not in_treasury or not dates:
            continue
        if label.startswith('nominal'):
            section = 'nominal'
            continue
        if label.startswith('inflation indexed'):
            section = 'real'
            continue
        if label.startswith('inflation-indexed long-term'):
            section = None
        sid = ('DFII10' if label=='10-year' and section=='real' else
               'DGS2' if label=='2-year' and section=='nominal' else
               'DGS10' if label=='10-year' and section=='nominal' else None)
        if sid:
            for date,cell in zip(dates,row[1:]):
                if date:
                    series[sid].append({'date':date,'value':cell})
    series={sid:clean_rows(rows) for sid,rows in series.items()}
    series={sid:rows for sid,rows in series.items() if rows}
    if not series:
        raise FeedError('H.15未返回有效收益率；未将名义利率当成实际利率')
    release = re.search(r'Release date:\s*([A-Za-z]+ \d{1,2}, \d{4})',html)
    release_date = datetime.strptime(release.group(1),'%B %d, %Y').date().isoformat() if release else None
    return {'source_release_date':release_date,'series':series,'source':'美联储 H.15 官方日度发布','url':H15_URL,
            'observed_at':max(rows[-1]['date'] for rows in series.values()),
            'missing':[sid for sid in RATE_LABELS if sid not in series]}


def fetch_h15():
    return parse_h15(get_bytes(H15_URL,timeout=(4,7),deadline_seconds=12,request_headers={'Cache-Control':'no-cache'}).decode('utf-8-sig'))


def parse_rate_csv(content,sid):
    reader=csv.DictReader(StringIO(content.decode('utf-8-sig')))
    if not reader.fieldnames or sid not in reader.fieldnames:
        raise FeedError(f'{sid}单项下载未返回有效CSV')
    date_field=next((k for k in reader.fieldnames if k.lower() in ('date','observation_date')),reader.fieldnames[0])
    rows=clean_rows([{'date':r.get(date_field),'value':r.get(sid)} for r in reader])
    if not rows:
        raise FeedError(f'{sid}无有效观测值')
    return {'series':{sid:rows},'source':f'FRED 单项日线 · {sid}',
            'url':f'https://fred.stlouisfed.org/series/{sid}','observed_at':rows[-1]['date']}


def fetch_rate(sid):
    if sid not in RATE_LABELS:
        raise ValueError('unsupported rate series')
    start=(datetime.now(UTC)-timedelta(days=730)).date().isoformat()
    content=get_bytes('https://fred.stlouisfed.org/graph/fredgraph.csv',
        {'id':sid,'cosd':start},timeout=(4,6),deadline_seconds=12)
    return parse_rate_csv(content,sid)


def resolve_rates(feeds):
    # H.15 and these FRED series describe the same constant-maturity rates.
    # Retain provenance per observation and let fresher downloads revise overlaps.
    results={sid:{} for sid in RATE_LABELS}
    for key in RATE_KEYS:
        entry=feeds.get(key,{})
        data=entry.get('data') or {}
        for sid in RATE_LABELS:
            for row in clean_rows(data.get('series',{}).get(sid,[])):
                fetched=row.get('fetched_at',data.get('series_fetched',{}).get(sid,entry.get('fetched_at',0)))
                try:
                    fetched=float(fetched) if isinstance(fetched,(int,float)) else parse_time(fetched).timestamp()
                except (ValueError,TypeError):
                    fetched=0
                stamped={**row,'source':row.get('source',data.get('source','FRED')),'url':row.get('url',data.get('url','https://fred.stlouisfed.org/')),
                         'source_updated_at':row.get('source_updated_at',data.get('source_updated_at')),
                         'source_release_date':row.get('source_release_date',data.get('source_release_date')),
                         'feed_key':key,'fetched_at':fetched}
                old=results[sid].get(row['date'])
                priority = 3 if key.startswith('rates:treasury_') else 2 if key=='rates:h15' else 1
                stamped['priority']=priority
                if old is None or (priority,fetched)>=(old.get('priority',1),old['fetched_at']):
                    results[sid][row['date']]=stamped
    return {sid:[bydate[d] for d in sorted(bydate)] for sid,bydate in results.items()}


def rate_summary(rows):
    rows=clean_rows(rows)
    if not rows:
        return None
    latest=rows[-1]
    delta=round((latest['value']-rows[-2]['value'])*100,4) if len(rows)>=2 else None
    if delta is not None and abs(delta)<1e-8:
        delta=0.
    return {**latest,'count':len(rows),'change_bp':delta,
            'direction':'样本不足' if delta is None else ('上升' if delta>0 else '下降' if delta<0 else '持平'),
            'previous_date':rows[-2]['date'] if len(rows)>=2 else None,
            'previous_value':rows[-2]['value'] if len(rows)>=2 else None,
            'change5_bp':round((latest['value']-rows[-6]['value'])*100,4) if len(rows)>=6 else None}


def parse_treasury_xml(content,kind):
    fields={'real':{'TC_10YEAR':'DFII10'},'nominal':{'BC_2YEAR':'DGS2','BC_10YEAR':'DGS10'}}
    if kind not in fields:
        raise ValueError('unsupported curve')
    try:
        root=ElementTree.fromstring(content)
    except ElementTree.ParseError as exc:
        raise FeedError('财政部未返回有效XML') from exc
    series={sid:[] for sid in fields[kind].values()}
    for entry in root.iter():
        if entry.tag.split('}')[-1]!='entry':
            continue
        cells={node.tag.split('}')[-1]:node.text for node in entry.iter()}
        date=(cells.get('NEW_DATE') or '')[:10]
        updated=cells.get('updated')
        if updated:
            try:
                updated=valid_time(updated)
            except (ValueError,TypeError,FeedError):
                updated=None
        for field,sid in fields[kind].items():
            series[sid].append({'date':date,'value':cells.get(field),'source_updated_at':updated})
    series={sid:clean_rows(rows) for sid,rows in series.items()}
    if not any(series.values()):
        raise FeedError('财政部XML无有效收益率')
    name='美国财政部 · 实际CMT日线（TIPS）' if kind=='real' else '美国财政部 · 名义CMT日线'
    return {'series':series,'source':name,'url':TREASURY_URL,
            'observed_at':max(rows[-1]['date'] for rows in series.values() if rows),
            'missing':[sid for sid,rows in series.items() if not rows]}


def fetch_treasury(kind):
    today=datetime.now(UTC).date()
    month=today.replace(day=1)
    payload=None
    errors=[]
    # Last month is needed near month rollover, but not on every normal request.
    for target in (month,(month-timedelta(days=1)).replace(day=1)):
        params={'data':'daily_treasury_real_yield_curve' if kind=='real' else 'daily_treasury_yield_curve',
                'field_tdr_date_value_month':target.strftime('%Y%m')}
        try:
            part=parse_treasury_xml(get_bytes(TREASURY_URL,params,timeout=(8,10),deadline_seconds=20,
                request_headers={'Cache-Control':'no-cache'}),kind)
            part['url']=TREASURY_URL+'?data='+params['data']+'&field_tdr_date_value_month='+params['field_tdr_date_value_month']
            for rows in part['series'].values():
                for row in rows:
                    row.update(source=part['source'],url=part['url'])
            if payload is None:
                payload=part
            else:
                for sid,rows in part['series'].items():
                    payload['series'][sid]=clean_rows(rows+payload['series'].get(sid,[]))
            if payload and all(len(rows)>=6 for rows in payload['series'].values()):
                break
        except FeedError as exc:
            errors.append(str(exc))
            if payload is None and '无有效收益率' not in str(exc):
                raise FeedError('财政部当月直连失败：'+str(exc),retry_after=exc.retry_after) from exc
    if payload is None:
        raise FeedError('财政部直连失败：'+'；'.join(errors))
    payload['observed_at']=max(rows[-1]['date'] for rows in payload['series'].values() if rows)
    return payload


def merge_rate_payload(previous,new,old_fetched,new_fetched):
    """A successful response containing older dates cannot delete newer observations."""
    previous=previous or {}
    raw_dates={sid:rows[-1]['date'] for sid,raw in new.get('series',{}).items() if (rows:=clean_rows(raw))}
    old_dates={sid:rows[-1]['date'] for sid,raw in previous.get('series',{}).items() if (rows:=clean_rows(raw))}
    merged={}
    for payload,fetched in [(previous,old_fetched),(new,new_fetched)]:
        for sid,raw in payload.get('series',{}).items():
            bydate=merged.setdefault(sid,{})
            for row in clean_rows(raw):
                bydate[row['date']]={**row,'fetched_at':row.get('fetched_at',fetched),
                    'source':row.get('source',payload.get('source','FRED')),
                    'url':row.get('url',payload.get('url','')),
                    'source_updated_at':row.get('source_updated_at',payload.get('source_updated_at')),
                    'source_release_date':row.get('source_release_date',payload.get('source_release_date'))}
    series={sid:[v[d] for d in sorted(v)][-1600:] for sid,v in merged.items() if v}
    regressed=[sid for sid,date in old_dates.items() if raw_dates.get(sid,'')<date]
    return {**new,'series':series,'checked_latest_dates':raw_dates,'latest_check_at':new_fetched,
            'source_regressed':regressed,
            'observed_at':max(rows[-1]['date'] for rows in series.values())}
