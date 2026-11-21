"""GOLD INTELLIGENCE V1.5: rendering reads local snapshots only."""
from datetime import datetime, timezone
from html import escape
import base64
import math
import os
import sqlite3
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from gold_intelligence.feeds import FRED_IDS, MARKETS, normalize_news, parse_time
from gold_intelligence.models import classify_news, forecast_model
from gold_intelligence.service import DataHub, default_specs
from gold_intelligence.yields import resolve_rates, rate_summary
from gold_intelligence.yields_ui import render_rate_card, render_yields
from gold_intelligence.domestic_ui import render_domestic
from gold_intelligence.logic_ui import render_logic
from gold_intelligence.intelligence import forecast_readiness, important_factors, completed_model_market
from gold_intelligence.prediction_ui import render_prediction_center
from gold_intelligence.assistant_ui import render_assistant
from gold_intelligence.activity import activity_metrics
from gold_intelligence.speeches import collected_speeches
from gold_intelligence.event_analysis import recent_messages
from gold_intelligence.journal import AnalysisJournal, snapshot_payload
from gold_intelligence.context_ui import render_activity, render_policy_energy, render_refresh_comparison, render_news_stress, render_message_center

BASE = Path(__file__).resolve().parent
TZ = ZoneInfo('Asia/Shanghai')
ICON = BASE / 'assets' / 'gold-icon-256.png'
st.set_page_config(page_title='GOLD INTELLIGENCE', page_icon=str(ICON), layout='wide')
st.markdown('''<style>
.stApp{background:#0b1020;color:#e9eef7}
[data-testid="stMainBlockContainer"]{padding-top:2rem;padding-bottom:3rem}
[data-testid="stHeader"]{background:#0b1020}
[data-testid="stSidebar"]{background:#111a2b;color:#e9eef7}
[data-testid="stSidebar"] :is(p,label,h1,h2,h3){color:#dbe4f2}
[data-testid="stMetric"]{background:#142039;border:1px solid #2a3852;padding:13px;border-radius:13px}
.stApp [data-testid="stMetricValue"]{font-size:clamp(1.15rem,2.1vw,2rem)!important;line-height:1.3}
.stApp [data-testid="stMetricValue"] p{font-size:inherit!important}
.stApp [data-testid="stMetricLabel"] p{white-space:normal!important;overflow:visible;text-overflow:clip}
.hero{padding:14px 20px;border-radius:17px;background:linear-gradient(120deg,#172640,#111827 60%,#382b18);border:1px solid #66502d;margin-bottom:12px}
.kicker{color:#d8b36b;font-size:11px;letter-spacing:2px;font-weight:700}
.hero h1{color:#f5f1e8;margin:4px 0;padding:0;line-height:1.2;font-size:28px}.hero p{color:#afbdd1;margin:0}
.card{background:#121d30;border:1px solid #2a3852;border-radius:13px;padding:13px 15px;margin:8px 0}
.small{color:#9eacc2;font-size:12px}
.priority-alert{border:2px solid;border-radius:13px;background:#17233b;padding:16px 20px;margin:8px 0 16px;font-size:16px}
.priority-alert b{font-size:19px}.priority-alert div{margin-top:6px}
.factor-focus{border:2px solid;border-radius:14px;background:#142039;padding:18px;margin:6px 0 16px;min-height:250px}
.factor-priority{font-size:16px;font-weight:700}.factor-value{font-size:30px;font-weight:700;margin:8px 0}
.factor-focus p{margin:10px 0}.scenario-row{display:flex;gap:24px;flex-wrap:wrap;font-size:18px;font-weight:700;margin:12px 0}
</style>''', unsafe_allow_html=True)


@st.cache_resource
def get_hub(collection_version):
    cache_path = os.environ.get('GOLD_CACHE_DIR', str(BASE / 'data' / 'cache'))
    specs = default_specs()  # V1.3: long history plus independent Treasury freshness feeds
    return DataHub(cache_path, specs=specs)


@st.cache_resource
def get_journal():
    return AnalysisJournal(BASE / 'data' / 'state' / 'analysis.sqlite')


@st.cache_data(ttl=3600, show_spinner=False, max_entries=24)
def cached_forecast(market, fred, reference, model_version):
    result = forecast_model(market, fred, reference)
    if result:
        result['generated_at'] = datetime.now(timezone.utc).isoformat()
        result['model_version'] = model_version
    return result


def stamp(value, with_time=True):
    if not value:
        return '暂无'
    try:
        dt = datetime.fromtimestamp(value, timezone.utc) if isinstance(value, (int, float)) else parse_time(value)
        return dt.astimezone(TZ).strftime('%Y-%m-%d %H:%M:%S' if with_time else '%Y-%m-%d')
    except (ValueError, TypeError, OverflowError):
        return str(value)


def to_series(rows, name):
    if not rows:
        return pd.Series(dtype=float, name=name)
    frame = pd.DataFrame(rows)
    return pd.Series(frame['value'].to_numpy(dtype=float), index=pd.to_datetime(frame['date']), name=name).sort_index()


def unpack(feeds, period):
    frames = []
    for ticker in MARKETS:
        data = feeds[f'market:{ticker}']['data']
        if data:
            name = {'GC=F':'Gold', 'DX-Y.NYB':'DXY', '^TNX':'US10Y', '^VIX':'VIX', 'CL=F':'WTI', 'BZ=F':'Brent', 'NG=F':'NaturalGas', 'GLD':'GLD', 'CNY=X':'USDCNY'}[ticker]
            frames.append(to_series(data['rows'], name))
    mkt = pd.concat(frames, axis=1, sort=True).sort_index() if frames else pd.DataFrame()
    if not mkt.empty:
        cutoff = pd.Timestamp.now(tz=TZ).tz_localize(None).normalize() - pd.DateOffset(years=period)
        mkt = mkt.loc[mkt.index >= cutoff]
        if 'Gold' in mkt:
            mkt = mkt.dropna(subset=['Gold'])
    macro = feeds['macro']['data'] or {}
    fred = {sid: to_series(macro.get('series', {}).get(sid, []), sid) for sid in FRED_IDS}
    for sid, rows in resolve_rates(feeds).items():
        fred[sid] = to_series(rows, sid)
    news = normalize_news([item for key, feed in feeds.items() if key.startswith('news:') and feed['data']
                           for item in feed['data'].get('items', [])], limit=240)
    return mkt, fred, news


def plot_layout(fig, height=350):
    fig.update_layout(template='plotly_dark', height=height, margin=dict(l=5,r=5,t=20,b=5),
                      paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                      yaxis_title='USD / troy oz', hovermode='x unified')
    return fig


def render_quality(feeds, storage_error):
    with st.expander('数据连接与更新状态', expanded=True):
        rows = []
        for feed in feeds.values():
            data = feed['data'] or {}
            rows.append({'模块':feed['label'], '状态':feed['status'],
                         '数据时间':stamp(data.get('observed_at'), feed['label']=='黄金现货参考报价'),
                         '采集时间（北京时间）':stamp(feed['fetched_at']),
                         '耗时（秒）':feed['duration'], '下次重试（秒）':feed['retry_in'] or None,
                         '错误详情':feed['error'] or '', '来源':data.get('source','')})
        st.dataframe(pd.DataFrame(rows), hide_index=True, width='stretch')
        st.caption('数据时间是来源提供的观测日期或报价更新时间；采集时间是本机下载时间。二者不能混用。新闻公告较旧不等于连接失败。')
        if storage_error:
            st.warning(storage_error)


def render_market(mkt, fred, feeds):
    quote = feeds['quote']
    quote_data = quote['data']
    gold = mkt['Gold'].dropna() if 'Gold' in mkt else pd.Series(dtype=float)
    st.markdown('### 01 / 全球黄金市场总览')
    cols = st.columns(5)
    if quote_data:
        cols[0].metric('黄金现货参考 / USD每盎司', f"${quote_data['price']:,.2f}")
        st.caption(f"现货来源：{quote_data['source']} · 来源更新时间：{stamp(quote_data['observed_at'])} 北京时间 · {quote['status']}")
        if quote['observation_old'] or quote['stale'] or quote['error']:
            st.warning('现货参考报价较旧或更新失败。请核对下方来源时间；休市时也可能停止更新。')
    elif len(gold):
        cols[0].metric('COMEX期货日线参考 / USD每盎司', f'${gold.iloc[-1]:,.2f}')
        st.caption('现货报价暂不可用；当前卡片显示 COMEX 期货日线参考。')
    else:
        cols[0].metric('黄金现货参考 / USD每盎司', '等待数据')
    for target, col, label, suffix in [(cols[1],'DXY','美元指数 DXY',''),(cols[4],'VIX','VIX恐慌指数','')]:
        s = mkt[col].dropna() if col in mkt else pd.Series(dtype=float)
        target.metric(label, f'{s.iloc[-1]:.2f}{suffix}' if len(s) else '暂无')
        if len(s):
            target.caption(f'观测日期：{s.index[-1].date()}')
    rates = resolve_rates(feeds)
    with cols[2]:
        render_rate_card(rates['DFII10'],'10年期实际收益率',compact=True,feeds=feeds,sid='DFII10')
    with cols[3]:
        render_rate_card(rates['DGS2'],'2年期美债收益率（名义）',compact=True,feeds=feeds,sid='DGS2')
    st.caption('免费参考行情可能延迟。图表及模型采用 COMEX 黄金期货日线；现货报价独立显示。')
    if not len(gold):
        st.info('历史行情正在后台采集或暂不可用。宏观、新闻和连接诊断仍可单独查看。')
        return
    st.markdown('### 02 / 黄金期货价格走势')
    st.caption(f"Yahoo Finance · GC=F（期货代理，非现货）· 日线最后日期：{gold.index[-1].date()} · 最新日线值：${gold.iloc[-1]:,.2f}")
    hist = gold.tail(250)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=hist.index,y=hist.values,name='GC=F 期货',line=dict(color='#d8b36b',width=2)))
    fig.add_trace(go.Scatter(x=hist.index,y=hist.rolling(20).mean(),name='20日均线',line=dict(color='#7e9bc8',dash='dot')))
    st.plotly_chart(plot_layout(fig), width='stretch')
    st.markdown('### 技术指标（期货日线）')
    delta = gold.diff()
    gain, loss = delta.clip(lower=0).rolling(14).mean(), -delta.clip(upper=0).rolling(14).mean()
    rsi = (100-100/(1+gain/loss.replace(0,np.nan))).dropna()
    a,b,c,d = st.columns(4)
    a.metric('RSI(14)', f'{rsi.iloc[-1]:.1f}' if len(rsi) else '暂无')
    b.metric('MA20', f'${gold.tail(20).mean():,.2f}' if len(gold)>=20 else '暂无')
    c.metric('MA50', f'${gold.tail(50).mean():,.2f}' if len(gold)>=50 else '暂无')
    vol = gold.pct_change(fill_method=None).tail(20).std()*math.sqrt(252)
    d.metric('20日年化波动率', f'{vol:.1%}' if pd.notna(vol) else '暂无')


def render_news(news, feeds):
    st.markdown('### 05 / 国际新闻与官方公告')
    st.caption('标题规则分类给出传导假设和验证条件，未执行 AI 深度解读或因果识别。BBC国际新闻与官方公告独立更新；各来源的覆盖范围不同。')
    status = feeds['news:gdelt']
    if status['error']:
        st.info(f"GDELT：{status['error']}。已独立采集 BBC 和官方 RSS；不会影响黄金报价。")
    if not news:
        st.info('新闻正在后台采集或暂不可用。')
    sources = ['全部'] + sorted({a['source'] for a in news})
    selected = st.selectbox('新闻来源', sources, key='news_source')
    items = [a for a in news if selected == '全部' or a['source'] == selected]
    for a in items[:20]:
        category,direction,chain,validation = classify_news(a)
        st.markdown(f'''<div class="card"><b>{escape(a['title'])}</b><br>
<span class="small">{escape(a['source'])} · {escape(a['domain'])} · {escape(a.get('time_kind','数据时间'))}：{escape(stamp(a['date']))} 北京时间</span><br><br>
<span class="small">分类：{escape(category)}<br>传导假设：{escape(chain)}<br>方向假设：{escape(direction)}<br>验证：{escape(validation)}</span><br>
<a href="{escape(a['url'],quote=True)}" target="_blank" rel="noopener noreferrer">查看原文 ↗</a></div>''', unsafe_allow_html=True)


def render_macro(fred, feeds):
    render_yields(feeds)
    st.markdown('### 美国宏观经济指标')
    labels = {'DFII10':('10年期实际收益率','%','日度'),'DGS2':('2年期名义收益率','%','日度'),'DGS10':('10年期名义收益率','%','日度'),
              'T10YIE':('10年期通胀预期','%','日度'),'CPIAUCSL':('CPI指数','指数','月度'),
              'PCEPI':('PCE价格指数','指数','月度'),'UNRATE':('失业率','%','月度'),
              'FEDFUNDS':('联邦基金有效利率','%','月度'),'PAYEMS':('非农就业人数','千人','月度')}
    macro = feeds['macro']['data'] or {}
    rows = []
    rate_rows = resolve_rates(feeds)
    for sid,(label,unit,freq) in labels.items():
        s = fred[sid].dropna()
        old = len(s) and (datetime.now(TZ).date() - s.index[-1].date()).days > (7 if freq=='日度' else 75)
        info = rate_summary(rate_rows.get(sid,[]))
        acquired = info.get('fetched_at') if info else macro.get('series_fetched',{}).get(sid)
        rows.append({'指标':label,'最新值':f'{s.iloc[-1]:,.2f} {unit}' if len(s) else '暂无',
                     '观测期':str(s.index[-1].date()) if len(s) else '暂无','频率':freq,
                     '采集时间（北京时间）':stamp(acquired),
                     '较上一观测日（基点）':info['change_bp'] if info else None,
                     '来源':info.get('source','FRED') if info else 'FRED',
                     '状态':'本轮未更新，保留历史' if not info and sid in macro.get('missing',[]) else ('观测期较旧' if old else ('已取得' if len(s) else '暂无'))})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width='stretch')
    st.caption('月度指标的日期是统计期，通常以月初标注，不是发布时间。宏观指标每6小时检查一次，不随行情每分钟重复下载。')


hub = get_hub('1.5.0')
st.sidebar.image(str(ICON), width=52)
st.sidebar.markdown('## GOLD INTELLIGENCE')
st.sidebar.caption('预测 · PPI/PMI · 官员讲话 · 历史与比价')
period_label = st.sidebar.selectbox('国际期货日线范围',['1年','2年','5年'],index=1)
period = {'1年':1,'2年':2,'5年':5}[period_label]
refresh = st.sidebar.selectbox('自动检查更新',['1分钟','5分钟','手动'],index=0)
interval = 300 if refresh == '5分钟' else 60
if refresh != '手动' or not st.session_state.get('initial_collection_v15'):
    hub.refresh_due(quote_interval=interval)
    st.session_state.initial_collection_v15 = True
if st.sidebar.button('↻ 后台刷新',width='stretch'):
    count = hub.refresh_due(force=True)
    st.session_state.manual_snapshot_pending = True
    st.sidebar.info(f'已提交 {count} 个更新任务。缓存保留；正在运行及冷却中的任务不会重复请求。')
if st.sidebar.button('检查最新消息与讲话',width='stretch'):
    keys=[s.key for s in default_specs() if s.key.startswith(('news:','speeches:','macro:','rates:'))]
    count=hub.refresh_due(force=True,keys=keys)
    st.session_state.manual_snapshot_pending=True
    st.sidebar.info(f'已提交 {count} 个消息/宏观检查任务；限流冷却中的来源继续等待。')
st.sidebar.caption('现货60秒 · 日线1小时 · 收益率15分钟 · 宏观6小时\n\n主要新闻/理事会讲话5分钟 · 地区讲话15分钟；失败自动退避。检查不等于来源一定有新发布。')
st.sidebar.divider()
st.sidebar.caption('V1.5 · 消息追踪与经济强弱版')
st.sidebar.caption('无需付费 AI API；免费行情可能延迟。')
icon_data = base64.b64encode(ICON.read_bytes()).decode()
st.markdown('<div class="hero"><img src="data:image/png;base64,' + icon_data + '" width="64" height="64" alt="黄金分析中心图标" style="float:right;margin-left:15px"><div class="kicker">GLOBAL GOLD & MACRO INTELLIGENCE</div><h1>全球黄金智能分析中心</h1><p>未来区间 · 重要因子提醒 · 免费数据问答</p></div>',unsafe_allow_html=True)
snapshot = hub.snapshot()
st.session_state.shown_revision = snapshot['revision']


@st.fragment(run_every='2s')
def poll_updates():
    if refresh != '手动':
        hub.refresh_due(quote_interval=interval)
    current = hub.snapshot()
    if current['revision'] != st.session_state.shown_revision:
        st.rerun()
    busy = sum(e['running'] for e in current['feeds'].values())
    ready = sum(e['data'] is not None for e in current['feeds'].values())
    st.caption(f'已取得 {ready}/{len(current["feeds"])} 个数据模块 · 后台任务 {busy} 个 · 先显示已有数据，更新完成后自动显示。')


poll_updates()
mkt, fred, news = unpack(snapshot['feeds'], period)
full_market, _, _ = unpack(snapshot['feeds'], 5)
full_market = completed_model_market(full_market)
readiness = forecast_readiness(full_market, snapshot['feeds'])
if refresh == '手动':
    readiness['schedule'] = '当前为手动检查模式，点击“后台刷新”后检查；取得新数据时重新计算'
forecast = cached_forecast(full_market, fred, readiness['reference'], '1.5.0') if readiness['ready'] else None
factors = important_factors(full_market, snapshot['feeds'])
context = {'market':full_market, 'fred':fred, 'feeds':snapshot['feeds'], 'readiness':readiness, 'forecast':forecast, 'factors':factors, 'news':news}
context['activity']=activity_metrics(snapshot['feeds'])
context['speeches']=collected_speeches(snapshot['feeds'])
context['messages']=recent_messages(news,context['speeches'])
collecting=any(e['running'] for key,e in snapshot['feeds'].items() if key.startswith(('market:','rates:','news:','speeches:','macro')))
try:
    context['journal']=get_journal()
    context['journal_state']=context['journal'].capture(snapshot_payload(context),
        force=st.session_state.get('manual_snapshot_pending',False),allow_write=bool(forecast and not collecting))
    if not collecting:st.session_state.manual_snapshot_pending=False
except (OSError,ValueError,RuntimeError,sqlite3.Error) as exc:
    st.warning('本机快照暂不能保存：'+str(exc)[:160]+'。当前行情和分析仍可查看。')


def render_current_context():
    render_activity(context)
    render_refresh_comparison(context)
    render_news_stress(context)
    with st.expander('加息预期、能源涨跌和地缘风险的传导'):
        render_policy_energy(context)


market_tab, logic_tab, domestic_tab, macro_tab, news_tab, chat_tab, quality_tab = st.tabs(['预测中心', '逻辑与历史', '国内比价', '宏观指标', '消息与讲话', '对话助手', '数据诊断'])
with market_tab:
    render_prediction_center(full_market, snapshot['feeds'], readiness, forecast, factors, extra_context=render_current_context)
    with st.expander('当前行情、走势图与技术指标'):
        render_market(mkt, fred, snapshot['feeds'])
with logic_tab:
    render_logic(snapshot['feeds'])
with domestic_tab:
    render_domestic(snapshot['feeds'])
with macro_tab:
    render_activity(context)
    render_macro(fred, snapshot['feeds'])
with news_tab:
    render_message_center(context)
with chat_tab:
    render_assistant(context)
with quality_tab:
    render_quality(snapshot['feeds'], snapshot['storage_error'])
st.caption('GOLD INTELLIGENCE V1.5 · 黄金研究工具 · 统计模型不保证未来价格。')
