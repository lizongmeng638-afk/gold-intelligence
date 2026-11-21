"""Official final-demand PPI and ISM activity measurements, never consensus data."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from html import unescape
import json
import math
from pathlib import Path
import re

from .feeds import FeedError, get_bytes, get_json, iso_now

API='https://api.bls.gov/publicAPI/v2/timeseries/data/'
ISM_BASE='https://www.ismworld.org/supply-management-news-and-reports/reports/ism-pmi-reports/'
MONTHS=('january','february','march','april','may','june','july','august','september','october','november','december')
SNAPSHOT=Path(__file__).resolve().parents[1]/'data/reference/activity_snapshot.json'


def text_only(html):
    html=re.sub(r'<(script|style)\b[^>]*>.*?</\1>',' ',html,flags=re.I|re.S)
    return re.sub(r'\s+',' ',unescape(re.sub(r'<[^>]+>',' ',html))).strip()


def bls_rows(payload,sid,now=None):
    now=now or datetime.now(timezone.utc)
    if payload.get('status')!='REQUEST_SUCCEEDED':
        raise FeedError('BLS API未成功：'+'；'.join(payload.get('message',[]))[:160])
    series=next((s for s in payload.get('Results',{}).get('series',[]) if s.get('seriesID')==sid),None)
    if not series:raise FeedError(sid+'未返回序列')
    rows={}
    for row in series.get('data',[]):
        if not re.fullmatch(r'M(0[1-9]|1[0-2])',str(row.get('period',''))):continue
        try:
            month=f"{int(row['year']):04d}-{int(row['period'][1:]):02d}"
            value=float(row['value'])
        except (ValueError,KeyError,TypeError):continue
        if month>=now.strftime('%Y-%m') or not math.isfinite(value) or value<=0:continue
        rows[month]={'date':month+'-01','value':value,'provisional':any(f.get('code')=='P' for f in row.get('footnotes',[]))}
    if not rows:raise FeedError(sid+'没有有效的完整统计月')
    return [rows[k] for k in sorted(rows)]


def ppi_measurement(sa,nsa):
    if not sa:raise FeedError('PPI缺少季调指数')
    latest=sa[-1];period=latest['date'][:7]
    y,m=map(int,period.split('-'));previous=f'{y-1:04d}-12' if m==1 else f'{y:04d}-{m-1:02d}'
    before_previous=f'{y-1:04d}-11' if m==1 else f'{y-1:04d}-12' if m==2 else f'{y:04d}-{m-2:02d}'
    sas={r['date'][:7]:r['value'] for r in sa};nsas={r['date'][:7]:r['value'] for r in nsa}
    change=lambda values,end,start:round((values[end]/values[start]-1)*100,1) if end in values and start in values else None
    py,pm=map(int,previous.split('-'))
    return {'period':period,'mom':change(sas,period,previous),'previous_mom':change(sas,previous,before_previous),
            'yoy':change(nsas,period,f'{y-1:04d}-{m:02d}'),'previous_yoy':change(nsas,previous,f'{py-1:04d}-{pm:02d}'),
            'index_sa':latest['value'],'provisional':latest.get('provisional',False),
            'source':'BLS官方API：最终需求PPI','url':API+'WPSFD4',
            'definition':'环比由WPSFD4季调指数计算，同比由WPUFD4未季调指数计算；修订值可能与新闻初值不同。','snapshot':False}


def fetch_ppi():
    with ThreadPoolExecutor(max_workers=2) as pool:
        fs={s:pool.submit(get_json,API+s) for s in ('WPSFD4','WPUFD4')}
        results={s:bls_rows(f.result(),s) for s,f in fs.items()}
    metric=ppi_measurement(results['WPSFD4'],results['WPUFD4'])
    return {'metric':metric,'rows':results,'observed_at':metric['period']+'-01','source':metric['source'],'url':metric['url']}


def parse_ism(html,kind,now=None):
    now=now or datetime.now(timezone.utc)
    text=text_only(html)
    if re.search(r'captcha|verify you are human|access denied',text,re.I):raise FeedError('ISM官方页要求访问验证，本轮未取得新数据')
    name='Manufacturing' if kind=='manufacturing' else 'Services'
    period_match=re.search(r'('+'|'.join(MONTHS)+r')\s+(20\d{2})\s+ISM',text,re.I)
    value=re.search(name+r'\s+PMI(?:[®™]|\s)*\s*at\s+([\d.]+)\s*%',text,re.I)
    if not period_match or not value:raise FeedError('ISM未返回可识别的官方报告，未采用')
    month=MONTHS.index(period_match[1].lower())+1;period=f'{period_match[2]}-{month:02d}'
    if period>=now.strftime('%Y-%m'):raise FeedError('ISM统计月份尚未结束，未采用')
    number=float(value[1])
    if not 0<=number<=100:raise FeedError('ISM PMI超出指数范围')
    # Read the previous figure from the opening release paragraph, not other subindexes.
    first=re.search(r'The\s+'+name+r'\s+PMI',text,re.I)
    paragraph=text[first.start():first.start()+800] if first else ''
    previous=re.search(r'(?:previous|September|October|November|December|January|February|March|April|May|June|July|August)(?:\s|’|\x27|s|figure|reading|of|at)*?([\d.]+)\s*percent',paragraph,re.I)
    # The official prose often says "September figure of 54.5 percent".
    fallback=re.search(r'(?:figure|reading)\s+of\s+([\d.]+)\s*percent',paragraph,re.I)
    previous_value=float((previous or fallback)[1]) if previous or fallback else None
    metric={'period':period,'value':number,'previous':previous_value,'source':'ISM '+name+' PMI',
            'url':ISM_BASE+('pmi' if kind=='manufacturing' else 'services')+'/'+MONTHS[month-1]+'/',
            'snapshot':False,'release_date':None}
    return {'metric':metric,'source':metric['source'],'url':metric['url'],'observed_at':period+'-01'}


def fetch_ism(kind):
    now=datetime.now(timezone.utc);year,month=now.year,now.month-1
    if month==0:year,month=year-1,12
    url=ISM_BASE+('pmi' if kind=='manufacturing' else 'services')+'/'+MONTHS[month-1]+'/'
    return parse_ism(get_bytes(url,timeout=(4,7),deadline_seconds=12,max_bytes=1_500_000).decode('utf-8-sig'),kind,now)


def activity_metrics(feeds):
    seed=json.loads(SNAPSHOT.read_text(encoding='utf-8'))
    result={}
    for kind,key in [('ppi','macro:ppi'),('manufacturing','macro:pmi_manufacturing'),('services','macro:pmi_services')]:
        entry=feeds.get(key,{})
        metric=(entry.get('data') or {}).get('metric')
        baseline=seed['metrics'][kind]
        error=entry.get('error','')
        if metric and metric['period']<baseline['period']:error='来源返回月份早于已核对快照；保留较新快照。'+error
        if not metric or metric['period']<baseline['period']:
            metric={**baseline,'verified_at':seed['verified_at'],'source_class':seed['source_class']}
        result[kind]={**metric,'connection_error':error,'last_checked':entry.get('checked_at') or entry.get('fetched_at'),
                      'status':entry.get('status','尚未检查'),'running':entry.get('running',False)}
    return result


def activity_assessment(metric,kind):
    if kind=='ppi':
        mom,yoy,previous=metric.get('mom'),metric.get('yoy'),metric.get('previous_mom')
        short='环比暂缺' if mom is None else '环比价格下降' if mom<0 else '环比价格持平' if mom==0 else '环比价格上涨'
        if mom is not None and previous is not None:
            if mom>0 and previous>0:short+='，涨速放缓' if mom<previous else '，涨速加快' if mom>previous else '，涨幅持平'
            elif mom<0 and previous<0:short+='，降幅收窄' if mom>previous else '，降幅扩大' if mom<previous else '，降幅持平'
            elif mom>0 and previous<=0:short+='，由持平或下降转为上涨'
            elif mom<0 and previous>=0:short+='，由持平或上涨转为下降'
        return {'label':short,'meaning':f'同比 {yoy:+.1f}%。PPI衡量生产端价格，不等于经济增长强弱；还需核心指标与预期值。' if yoy is not None else '同比样本不足，不补0；PPI不是增长强弱指标。',
                'path':'价格压力若推高加息预期、美元与实际收益率，可能压制黄金；保值需求也可能形成支持。'}
    value,previous=metric['value'],metric.get('previous')
    label='扩张' if value>50 else '收缩' if value<50 else '接近持平分界'
    if previous is not None:label+='且较上月改善' if value>previous else '但较上月回落' if value<previous else '，较上月持平'
    return {'label':label,'meaning':'50是该行业PMI的扩张/收缩分界；不是相对市场预期，也不是GDP增速。',
            'path':'经济活动偏强可能降低宽松预期；对黄金还要核对实际收益率、美元和需求变化，不能直接等同利空。'}
