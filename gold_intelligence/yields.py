"""Independent daily Treasury constant-maturity rates and change calculations."""
from datetime import datetime, timedelta
from io import StringIO
import csv
import math
import re

from .domestic import table_rows
from .feeds import FeedError, UTC, get_bytes, parse_time, valid_time

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
    return {'series':series,'source':'美联储 H.15 官方日度发布','url':H15_URL,
            'observed_at':max(rows[-1]['date'] for rows in series.values()),
            'missing':[sid for sid in RATE_LABELS if sid not in series]}


def fetch_h15():
    return parse_h15(get_bytes(H15_URL,timeout=(4,7),deadline_seconds=12).decode('utf-8-sig'))


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
    for key in ['macro','rates:h15','rates:DFII10','rates:DGS2']:
        entry=feeds.get(key,{})
        data=entry.get('data') or {}
        for sid in RATE_LABELS:
            for row in clean_rows(data.get('series',{}).get(sid,[])):
                fetched=data.get('series_fetched',{}).get(sid,entry.get('fetched_at',0))
                try:
                    fetched=float(fetched) if isinstance(fetched,(int,float)) else parse_time(fetched).timestamp()
                except (ValueError,TypeError):
                    fetched=0
                stamped={**row,'source':data.get('source','FRED'),'url':data.get('url','https://fred.stlouisfed.org/'),
                         'fetched_at':fetched}
                old=results[sid].get(row['date'])
                if old is None or fetched>=old['fetched_at']:
                    results[sid][row['date']]=stamped
    return {sid:[bydate[d] for d in sorted(bydate)] for sid,bydate in results.items()}


def rate_summary(rows):
    rows=clean_rows(rows)
    if not rows:
        return None
    latest=rows[-1]
    delta=(latest['value']-rows[-2]['value'])*100 if len(rows)>=2 else None
    if delta is not None and abs(delta)<1e-8:
        delta=0.
    return {**latest,'count':len(rows),'change_bp':delta,
            'direction':'样本不足' if delta is None else ('上升' if delta>0 else '下降' if delta<0 else '持平'),
            'previous_date':rows[-2]['date'] if len(rows)>=2 else None,
            'previous_value':rows[-2]['value'] if len(rows)>=2 else None,
            'change5_bp':(latest['value']-rows[-6]['value'])*100 if len(rows)>=6 else None}
