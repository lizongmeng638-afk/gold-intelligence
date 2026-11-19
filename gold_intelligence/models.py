import math
import numpy as np
import pandas as pd
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge

def normal_cdf(x,mu,sigma):
    return .5*(1+math.erf((x-mu)/(max(sigma,1e-8)*math.sqrt(2))))

def forecast_model(mkt, fred, spot):
    gold=mkt["Gold"].dropna()
    if len(gold)<90: return None
    x=pd.DataFrame(index=mkt.index)
    x["gold_r1"]=mkt["Gold"].pct_change(fill_method=None)
    x["gold_r5"]=mkt["Gold"].pct_change(5, fill_method=None)
    x["gold_r20"]=mkt["Gold"].pct_change(20, fill_method=None)
    if "DXY" in mkt and mkt["DXY"].notna().sum()>60:
        x["dxy_r1"]=mkt["DXY"].pct_change(fill_method=None)
        x["dxy_r5"]=mkt["DXY"].pct_change(5, fill_method=None)
    real=fred.get("DFII10",pd.Series(dtype=float))
    if len(real):
        ry=real.reindex(real.index.union(x.index)).sort_index().ffill().reindex(x.index)
        x["real_yield_d1"]=ry.diff()
        x["real_yield_d5"]=ry.diff(5)
    elif "US10Y" in mkt and mkt["US10Y"].notna().sum()>60:
        x["nominal_yield_d1"]=mkt["US10Y"].diff()
        x["nominal_yield_d5"]=mkt["US10Y"].diff(5)
    for col,prefix in [("VIX","vix"),("WTI","oil"),("GLD","gld")]:
        if col in mkt and mkt[col].notna().sum()>60:
            x[prefix+"_r1"]=mkt[col].pct_change(fill_method=None)
            if col!="GLD": x[prefix+"_r5"]=mkt[col].pct_change(5, fill_method=None)
    x=x.replace([np.inf,-np.inf],np.nan)
    x=x[[c for c in x if x[c].notna().sum()>=max(60,int(len(x)*.55))]].dropna()
    y=gold.pct_change(fill_method=None).shift(-1).rename("target")
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
        pred=float(gold.pct_change(fill_method=None).tail(20).mean()); sigma=float(gold.pct_change(fill_method=None).tail(60).std()); acc=None
        label="历史统计基线"
    vol=max(sigma if np.isfinite(sigma) else 0,float(gold.pct_change(fill_method=None).tail(60).std()),.0025)
    drift=float(np.clip(.65*pred+.35*gold.pct_change(fill_method=None).tail(20).mean(),-.003,.003))
    rows=[]
    for h,name in [(1,"1个交易日（约24小时）"),(3,"3个交易日"),(7,"7个交易日"),(30,"30个交易日"),(90,"90个交易日")]:
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
            "date":gold.index[-1]+pd.offsets.BDay(h)})
    if x.index[-1] < gold.index[-1] - pd.Timedelta(days=7): return None
    return {"rows":rows,"vol":vol,"acc":acc,"label":label,"feature_date":str(x.index[-1].date()),
        "note":"周期按交易日计算；日期仅排除周末，未纳入交易所节假日。方向准确率仅为日线留出集结果，非各周期预测胜率，宏观历史值可能经过修订。短期使用时间顺序验证的Ridge多因子模型；长周期对短期漂移做衰减，区间由历史残差波动扩展。新闻事件暂不直接换算成固定涨跌幅。"}

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
    elif "US10Y" in mkt and mkt["US10Y"].notna().sum()>60:
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

