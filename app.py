import math
from io import StringIO
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
import yfinance as yf
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge

st.set_page_config(page_title="GOLD INTELLIGENCE", page_icon="🟡", layout="wide")
st.markdown("""
<style>
.stApp{background:#0b1020;color:#e9eef7}
[data-testid="stSidebar"]{background:#111a2b}
[data-testid="stMetric"]{background:#142039;border:1px solid #2a3852;padding:13px;border-radius:13px}
.hero{padding:22px 24px;border-radius:17px;background:linear-gradient(120deg,#172640,#111827 60%,#382b18);border:1px solid #66502d;margin-bottom:15px}
.kicker{color:#d8b36b;font-size:11px;letter-spacing:2px;font-weight:700}
.hero h1{color:#f5f1e8;margin:4px 0;font-size:30px}
.hero p{color:#afbdd1;margin:0}
.card{background:#121d30;border:1px solid #2a3852;border-radius:13px;padding:13px 15px;margin:8px 0}
.small{color:#9eacc2;font-size:12px}
</style>
""", unsafe_allow_html=True)

HEADERS = {"User-Agent":"Mozilla/5.0"}
TICKERS = {"spot":"XAUUSD=X","futures":"GC=F","DXY":"DX-Y.NYB","US10Y":"^TNX","VIX":"^VIX","WTI":"CL=F","GLD":"GLD","USDCNY":"CNY=X"}

@st.cache_data(ttl=300, show_spinner=False)
def market_data(period):
    raw = yf.download(list(TICKERS.values()), period=period, interval="1d",
                      auto_adjust=True, group_by="column", progress=False, threads=True)
    if raw is None or raw.empty:
        return pd.DataFrame(), "Yahoo Finance无数据"
    if isinstance(raw.columns, pd.MultiIndex):
        close = raw["Close"] if "Close" in raw.columns.get_level_values(0) else raw.xs("Close", axis=1, level=1)
    else:
        close = raw[["Close"]].copy()
        close.columns = [list(TICKERS.values())[0]]
    close = close.rename(columns={v:k for k,v in TICKERS.items()})
    close.index = pd.to_datetime(close.index)
    if getattr(close.index, "tz", None) is not None:
        close.index = close.index.tz_localize(None)
    close = close.sort_index()
    if "spot" in close and close["spot"].notna().sum() > 30:
        close["Gold"] = close["spot"]
        source = "Yahoo Finance XAUUSD=X（现货参考）"
    elif "futures" in close and close["futures"].notna().sum() > 30:
        close["Gold"] = close["futures"]
        source = "Yahoo Finance GC=F（COMEX期货代理，非现货）"
    else:
        return pd.DataFrame(), "未取得黄金行情"
    return close.dropna(subset=["Gold"]), source

@st.cache_data(ttl=300, show_spinner=False)
def intraday_gold(ticker):
    try:
        raw = yf.download(ticker, period="5d", interval="5m", progress=False, auto_adjust=True)
        if raw is None or raw.empty:
            return None
        if isinstance(raw.columns, pd.MultiIndex):
            s = raw["Close"].iloc[:,0]
        else:
            s = raw["Close"]
        s = s.dropna()
        return float(s.iloc[-1]) if len(s) else None
    except Exception:
        return None

@st.cache_data(ttl=3600, show_spinner=False)
def fred_series(sid):
    try:
        r = requests.get("https://fred.stlouisfed.org/graph/fredgraph.csv",
                         params={"id":sid}, headers=HEADERS, timeout=20)
        r.raise_for_status()
        df = pd.read_csv(StringIO(r.text))
        d, v = df.columns[0], sid if sid in df.columns else df.columns[1]
        df[d] = pd.to_datetime(df[d], errors="coerce")
        df[v] = pd.to_numeric(df[v].replace(".", np.nan), errors="coerce")
        df = df.dropna(subset=[d,v]).sort_values(d)
        return pd.Series(df[v].values, index=df[d], name=sid)
    except Exception:
        return pd.Series(dtype=float, name=sid)

@st.cache_data(ttl=3600, show_spinner=False)
def fred_bundle():
    ids = ["DFII10","DGS10","T10YIE","CPIAUCSL","PCEPI","UNRATE","FEDFUNDS","PAYEMS"]
    return {sid:fred_series(sid) for sid in ids}

@st.cache_data(ttl=600, show_spinner=False)
def gdelt_news():
    q = '(gold OR bullion OR "Federal Reserve" OR inflation OR "Treasury yields" OR "central bank" OR geopolitical OR war)'
    try:
        r = requests.get("https://api.gdeltproject.org/api/v2/doc/doc",
            params={"query":q,"mode":"ArtList","format":"json","maxrecords":50,"sort":"HybridRel","timespan":"24h"},
            headers=HEADERS,timeout=20)
        r.raise_for_status()
        items = r.json().get("articles",[])
        out=[]; seen=set()
        for a in items:
            title=str(a.get("title","")).strip()
            if not title or title.lower() in seen: continue
            seen.add(title.lower())
            stamp=str(a.get("seendate",""))
            try:
                dt=datetime.strptime(stamp[:14],"%Y%m%d%H%M%S").replace(tzinfo=timezone.utc).astimezone()
                stamp=dt.strftime("%Y-%m-%d %H:%M")
            except Exception: pass
            out.append({"title":title,"url":a.get("url",""),"domain":a.get("domain",""),"date":stamp})
        return out
    except Exception:
        return []

def normal_cdf(x,mu,sigma):
    return .5*(1+math.erf((x-mu)/(max(sigma,1e-8)*math.sqrt(2))))

def forecast_model(mkt, fred, spot):
    gold=mkt["Gold"].dropna()
    if len(gold)<90: return None
    x=pd.DataFrame(index=mkt.index)
    x["gold_r1"]=mkt["Gold"].pct_change()
    x["gold_r5"]=mkt["Gold"].pct_change(5)
    x["gold_r20"]=mkt["Gold"].pct_change(20)
    if "DXY" in mkt and mkt["DXY"].notna().sum()>60:
        x["dxy_r1"]=mkt["DXY"].pct_change()
        x["dxy_r5"]=mkt["DXY"].pct_change(5)
    real=fred.get("DFII10",pd.Series(dtype=float))
    if len(real):
        ry=real.reindex(x.index).ffill()
        x["real_yield_d1"]=ry.diff()
        x["real_yield_d5"]=ry.diff(5)
    elif "US10Y" in mkt:
        x["nominal_yield_d1"]=mkt["US10Y"].diff()
        x["nominal_yield_d5"]=mkt["US10Y"].diff(5)
    for col,prefix in [("VIX","vix"),("WTI","oil"),("GLD","gld")]:
        if col in mkt and mkt[col].notna().sum()>60:
            x[prefix+"_r1"]=mkt[col].pct_change()
            if col!="GLD": x[prefix+"_r5"]=mkt[col].pct_change(5)
    x=x.replace([np.inf,-np.inf],np.nan)
    x=x[[c for c in x if x[c].notna().sum()>=max(60,int(len(x)*.55))]].dropna()
    y=gold.pct_change().shift(-1).rename("target")
    train=x.join(y).dropna()
    if len(train)<60: return None
    X=train.drop(columns="target"); Y=train["target"]
    split=max(40,min(int(len(train)*.8),len(train)-10))
    pipe=Pipeline([("scale",StandardScaler()),("ridge",Ridge(alpha=8))])
    try:
        pipe.fit(X.iloc[:split],Y.iloc[:split])
        predv=pipe.predict(X.iloc[split:])
        err=Y.iloc[split:].values-predv
        sigma=float(np.std(err,ddof=1)) if len(err)>5 else float(Y.std())
        acc=float(np.mean(np.sign(predv)==np.sign(Y.iloc[split:].values))) if len(err)>5 else None
        pipe.fit(X,Y)
        pred=float(pipe.predict(x.iloc[[-1]][X.columns])[0])
        label="Ridge多因子模型"
    except Exception:
        pred=float(gold.pct_change().tail(20).mean()); sigma=float(gold.pct_change().tail(60).std()); acc=None
        label="历史统计基线"
    vol=max(sigma if np.isfinite(sigma) else 0,float(gold.pct_change().tail(60).std()),.0025)
    drift=float(np.clip(.65*pred+.35*gold.pct_change().tail(20).mean(),-.003,.003))
    rows=[]
    for h,name in [(1,"24小时"),(3,"3天"),(7,"7天"),(30,"30天"),(90,"90天")]:
        mu=drift*h*math.exp(-h/35)
        sig=vol*math.sqrt(h)*(1+min(h,90)*.003)
        center=spot*math.exp(mu)
        p_up=1-normal_cdf(.35*sig,mu,sig)
        p_down=normal_cdf(-.35*sig,mu,sig)
        p_flat=max(0,1-p_up-p_down); total=p_up+p_down+p_flat
        rows.append({"h":h,"name":name,"center":center,
            "low80":spot*math.exp(mu-1.2816*sig),"high80":spot*math.exp(mu+1.2816*sig),
            "low95":spot*math.exp(mu-1.96*sig),"high95":spot*math.exp(mu+1.96*sig),
            "up":p_up/total,"flat":p_flat/total,"down":p_down/total,
            "date":gold.index[-1]+pd.Timedelta(days=h)})
    return {"rows":rows,"vol":vol,"acc":acc,"label":label,
        "note":"短期使用时间顺序验证的Ridge多因子模型；长周期对短期漂移做衰减，区间由历史残差波动扩展。新闻事件暂不直接换算成固定涨跌幅。"}

def factor_cards(mkt, fred):
    out=[]
    if "DXY" in mkt:
        s=mkt["DXY"].dropna()
        if len(s)>6:
            ch=(s.iloc[-1]/s.iloc[-6]-1)*100
            out.append(("美元指数 DXY",f"5日 {ch:+.2f}%","偏空" if ch>.25 else ("偏多" if ch<-.25 else "中性"),
                "美元走强通常压制美元计价黄金；走弱通常提供支撑。"))
    ry=fred.get("DFII10",pd.Series(dtype=float))
    if len(ry)>6:
        ch=ry.iloc[-1]-ry.iloc[-6]
        out.append(("10年期实际收益率",f"5个观测日 {ch:+.2f}个百分点","偏空" if ch>.05 else ("偏多" if ch<-.05 else "中性"),
            "实际收益率上升通常提高持有无息黄金的机会成本。"))
    elif "US10Y" in mkt:
        s=mkt["US10Y"].dropna()
        if len(s)>6:
            ch=s.iloc[-1]-s.iloc[-6]
            out.append(("美国10年期名义收益率",f"5日 {ch:+.2f}个百分点","偏空" if ch>.05 else ("偏多" if ch<-.05 else "中性"),
                "这是名义收益率替代指标，不等于实际收益率。"))
    for col,name in [("VIX","VIX风险情绪"),("WTI","WTI原油")]:
        if col in mkt:
            s=mkt[col].dropna()
            if len(s)>6:
                ch=(s.iloc[-1]/s.iloc[-6]-1)*100
                direction=("偏多" if ch>8 else ("偏空" if ch<-8 else "中性")) if col=="VIX" else "条件性"
                text="恐慌情绪上升可能增加避险需求，但不保证资金流入黄金。" if col=="VIX" else "油价上涨可能影响通胀预期，也可能反映供需变化，方向并非单一。"
                out.append((name,f"5日 {ch:+.2f}%",direction,text))
    return out

def classify_news(a):
    t=a["title"].lower()
    if any(k in t for k in ["hawkish","higher for longer","rate hike","restrictive policy"]):
        return ("美联储偏鹰/利率预期上升","偏空","鹰派预期 → 实际收益率/美元可能上升 → 黄金机会成本上升","观察DXY和实际收益率是否同步上行。")
    if any(k in t for k in ["dovish","rate cut","cut rates","easing cycle","lower rates"]):
        return ("美联储偏鸽/降息预期","偏多","降息预期增强 → 实际收益率可能下降 → 黄金吸引力上升","观察实际收益率与DXY是否同步回落。")
    if any(k in t for k in ["ceasefire","peace deal","truce","de-escalation"]):
        return ("地缘政治缓和","偏空","冲突缓和 → 避险需求可能下降 → 黄金避险溢价可能回落","观察VIX、油价和金价实际反应。")
    if any(k in t for k in ["war","missile","attack","invasion","escalation","conflict","sanctions"]):
        return ("地缘政治冲突/风险升级","偏多","冲突升级 → 风险厌恶上升 → 避险需求可能增加","观察VIX、美元、实际收益率是否抵消避险买盘。")
    if any(k in t for k in ["cpi","inflation","pce","consumer prices"]):
        return ("通胀数据/预期","条件性","通胀变化 → 利率路径调整 → 实际收益率和美元变化 → 黄金重新定价","比较实际值与预期，并观察实际收益率。")
    if any(k in t for k in ["nonfarm","payroll","jobs report","unemployment","jobless claims"]):
        return ("美国就业数据","条件性","就业强弱 → 美联储预期 → 美元和收益率 → 黄金","核对数据与预期差及公布后市场反应。")
    if any(k in t for k in ["central bank","gold reserves","gold buying","gold purchases"]):
        return ("央行购金/黄金储备","偏多","央行增加黄金储备 → 官方部门需求增加 → 中长期需求支撑","核实官方来源、统计期和净购金数量。")
    if any(k in t for k in ["tariff","trade war","trade tensions"]):
        return ("关税/贸易摩擦","条件性","贸易不确定性 → 风险偏好与通胀预期变化 → 美元/收益率 → 黄金","观察美元、实际收益率和VIX的同步反应。")
    return ("一般宏观/黄金新闻","待判断","新闻事件 → 待确认传导渠道 → 观察美元、实际收益率和黄金反应","仅凭标题不足以生成方向性交易信号。")

# Sidebar
st.sidebar.markdown("## 🟡 GOLD INTELLIGENCE")
st.sidebar.caption("国际黄金 · 宏观经济 · 事件因果 · 预测区间")
period_label=st.sidebar.selectbox("历史数据范围",["1年","2年","5年"],index=1)
period={"1年":"1y","2年":"2y","5年":"5y"}[period_label]
refresh=st.sidebar.selectbox("自动刷新",["手动","5分钟","15分钟"],index=1)
if refresh!="手动":
    try:
        from streamlit_autorefresh import st_autorefresh
        st_autorefresh(interval=300000 if refresh=="5分钟" else 900000,key="refresh")
    except Exception: st.sidebar.caption("自动刷新组件不可用，请手动刷新。")
if st.sidebar.button("↻ 立即刷新",use_container_width=True):
    st.cache_data.clear(); st.rerun()
st.sidebar.divider()
st.sidebar.caption("免费数据源版本 · V1.0")
st.sidebar.caption("免费行情可能延迟、限流，不保证逐笔实时。")

st.markdown('<div class="hero"><div class="kicker">GLOBAL GOLD & MACRO INTELLIGENCE</div><h1>全球黄金智能分析中心</h1><p>事件 → 因果 → 市场验证 → 预测幅度与区间</p></div>',unsafe_allow_html=True)

with st.spinner("正在获取国际行情、宏观数据和新闻…"):
    mkt,gold_source=market_data(period)
    fred=fred_bundle()
    news=gdelt_news()

if mkt.empty or "Gold" not in mkt:
    st.error("当前未取得黄金行情。请检查网络后点击立即刷新。")
    st.stop()

ticker="XAUUSD=X" if "XAUUSD=X" in gold_source else "GC=F"
intra=intraday_gold(ticker)
gold=mkt["Gold"].dropna()
last=float(intra if intra is not None else gold.iloc[-1])
change=(gold.iloc[-1]/gold.iloc[-2]-1)*100 if len(gold)>1 else 0
fc=forecast_model(mkt,fred,last)
factors=factor_cards(mkt,fred)

st.markdown("### 01 / 全球黄金市场总览")
dxy=mkt["DXY"].dropna() if "DXY" in mkt else pd.Series(dtype=float)
real=fred.get("DFII10",pd.Series(dtype=float))
vix=mkt["VIX"].dropna() if "VIX" in mkt else pd.Series(dtype=float)
cols=st.columns(4)
cols[0].metric("国际黄金 / USD每盎司",f"${last:,.2f}",f"{change:+.2f}%日线")
cols[1].metric("美元指数 DXY",f"{dxy.iloc[-1]:.2f}" if len(dxy) else "暂无",f"{(dxy.iloc[-1]/dxy.iloc[-6]-1)*100:+.2f}% / 5日" if len(dxy)>6 else None)
cols[2].metric("10年期实际收益率",f"{real.iloc[-1]:.2f}%" if len(real) else "暂无","FRED日度数据" if len(real) else "未取得")
cols[3].metric("VIX恐慌指数",f"{vix.iloc[-1]:.2f}" if len(vix) else "暂无","风险情绪参考")
st.caption(f"黄金来源：{gold_source}；报价类型：{'Yahoo 5分钟盘中参考（可能延迟）' if intra is not None else '最近日线收盘价'}；日线最后日期：{gold.index[-1].date()}。")

st.markdown("### 02 / 黄金价格走势")
fig=go.Figure()
hist=gold.tail(250)
fig.add_trace(go.Scatter(x=hist.index,y=hist.values,name="黄金",line=dict(color="#d8b36b",width=2)))
fig.add_trace(go.Scatter(x=hist.index,y=hist.rolling(20).mean(),name="20日均线",line=dict(color="#7e9bc8",dash="dot")))
fig.update_layout(template="plotly_dark",height=370,margin=dict(l=5,r=5,t=20,b=5),paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(0,0,0,0)",yaxis_title="USD / troy oz",hovermode="x unified")
st.plotly_chart(fig,use_container_width=True)

st.markdown("### 03 / 关键驱动因素")
if factors:
    for name,ch,direction,desc in factors:
        st.markdown(f'<div class="card"><b>{name}</b>　<span style="color:#d8b36b">{ch}</span><br><span class="small">黄金影响：{direction} · {desc}</span></div>',unsafe_allow_html=True)
else: st.info("宏观驱动数据不足。")

st.markdown("### 04 / 量化预测与价格区间")
st.caption("预测是统计情景，不是保证价格。区间来自历史模型误差与波动率；新闻暂不直接换算为固定涨跌幅。")
if fc:
    a,b,c=st.columns(3)
    a.metric("模型验证方向准确率",f"{fc['acc']:.1%}" if fc["acc"] is not None else "样本不足")
    b.metric("日波动率估计",f"{fc['vol']*100:.2f}%")
    c.metric("模型",fc["label"])
    table=pd.DataFrame(fc["rows"])[["name","center","low80","high80","low95","high95","up","flat","down"]]
    table.columns=["周期","中心预测价","80%下沿","80%上沿","95%下沿","95%上沿","上涨概率","震荡概率","下跌概率"]
    for col in ["中心预测价","80%下沿","80%上沿","95%下沿","95%上沿"]: table[col]=table[col].map(lambda x:f"${x:,.2f}")
    for col in ["上涨概率","震荡概率","下跌概率"]: table[col]=table[col].map(lambda x:f"{x:.1%}")
    st.dataframe(table,use_container_width=True,hide_index=True)
    f=go.Figure()
    f.add_trace(go.Scatter(x=gold.tail(90).index,y=gold.tail(90).values,name="历史",line=dict(color="#d8b36b",width=2)))
    dates=[r["date"] for r in fc["rows"]]
    f.add_trace(go.Scatter(x=dates,y=[r["high80"] for r in fc["rows"]],line=dict(width=0),showlegend=False,hoverinfo="skip"))
    f.add_trace(go.Scatter(x=dates,y=[r["low80"] for r in fc["rows"]],fill="tonexty",fillcolor="rgba(216,179,107,.16)",line=dict(width=0),name="80%情景区间"))
    f.add_trace(go.Scatter(x=dates,y=[r["center"] for r in fc["rows"]],mode="lines+markers",name="中心预测",line=dict(color="#72b89c",dash="dash")))
    f.update_layout(template="plotly_dark",height=330,margin=dict(l=5,r=5,t=15,b=5),paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(0,0,0,0)",yaxis_title="USD / oz")
    st.plotly_chart(f,use_container_width=True)
    st.caption(fc["note"])
else: st.warning("历史行情不足，暂不能生成预测。")

st.markdown("### 05 / 国际事件：事件 → 因果 → 结论")
st.caption("GDELT新闻标题初步分类；新闻转载去重不完全。事件方向需市场验证。")
if news:
    for a in news[:15]:
        category,direction,chain,validation=classify_news(a)
        link=f'<a href="{a["url"]}" target="_blank">查看原文 ↗</a>' if a["url"] else ""
        color="#70c69b" if direction=="偏多" else ("#e17d7d" if direction=="偏空" else "#d8b36b")
        st.markdown(f'<div class="card"><b>{a["title"]}</b><br><span class="small">{a["domain"]} · {a["date"]}</span><br><br><span class="small">事件：{category}<br>因果：{chain}<br>结论：<b style="color:{color}">{direction}</b><br>验证：{validation}<br>幅度：事件特定涨跌幅需历史事件回测；请参考上方整体量化预测区间。</span><br>{link}</div>',unsafe_allow_html=True)
else: st.info("新闻源暂时不可用，请稍后刷新。")

st.markdown("### 06 / 美国宏观经济指标")
labels={"DFII10":("10年期实际收益率","%","日度"),"DGS10":("10年期名义收益率","%","日度"),"T10YIE":("10年期通胀预期","%","日度"),"CPIAUCSL":("CPI指数","指数","月度"),"PCEPI":("PCE价格指数","指数","月度"),"UNRATE":("失业率","%","月度"),"FEDFUNDS":("联邦基金有效利率","%","月度"),"PAYEMS":("非农就业人数","千人","月度")}
rows=[]
for sid,(name,unit,freq) in labels.items():
    s=fred.get(sid,pd.Series(dtype=float)).dropna()
    rows.append({"指标":name,"最新值":f"{s.iloc[-1]:,.2f} {unit}" if len(s) else "暂无","数据日期":str(s.index[-1].date()) if len(s) else "暂无","频率":freq,"来源":"FRED"})
st.dataframe(pd.DataFrame(rows),use_container_width=True,hide_index=True)

st.markdown("### 07 / 技术指标")
delta=gold.diff(); gain=delta.clip(lower=0).rolling(14).mean(); loss=-delta.clip(upper=0).rolling(14).mean()
rsi=100-100/(1+gain/loss.replace(0,np.nan))
vol=gold.pct_change().tail(20).std()*math.sqrt(252)*100
a,b,c,d=st.columns(4)
a.metric("RSI(14)",f"{rsi.dropna().iloc[-1]:.1f}" if len(rsi.dropna()) else "暂无")
b.metric("MA20",f"${gold.rolling(20).mean().iloc[-1]:,.2f}")
b2=gold.rolling(50).mean().iloc[-1] if len(gold)>=50 else np.nan
c.metric("MA50",f"${b2:,.2f}" if pd.notna(b2) else "暂无")
d.metric("20日年化波动率",f"{vol:.1f}%" if pd.notna(vol) else "暂无")

st.markdown("### 08 / 数据来源与质量")
status=[
 {"模块":"黄金及市场行情","来源":gold_source+"；Yahoo Finance非官方接口","说明":"可能延迟、限流；盘中报价为5分钟数据尝试"},
 {"模块":"美元/收益率/VIX/原油/GLD","来源":"Yahoo Finance","说明":"免费数据可用性不保证；GLD价格不是ETF资金净流量"},
 {"模块":"美国宏观指标","来源":"FRED公共CSV下载","说明":"遵循日度/月度发布频率；不是实时数据"},
 {"模块":"国际新闻","来源":"GDELT DOC 2.0","说明":f"本次取得{len(news)}条；覆盖不完整"},
]
st.dataframe(pd.DataFrame(status),use_container_width=True,hide_index=True)
st.info("重要限制：免费数据不等于真正逐笔实时。事件卡片目前提供方向、因果路径和验证条件，不会凭新闻标题编造具体涨跌幅。要估计事件冲击幅度，下一阶段需建立历史事件样本并做事件研究回测。")
st.caption("GOLD INTELLIGENCE V1.0 · Mac本地研究工具 · 不构成投资建议。")
