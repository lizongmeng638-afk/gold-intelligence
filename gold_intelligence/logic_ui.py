"""A readable route from monetary history to price evidence and technical levels."""
from datetime import datetime
from html import escape
import json

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .gold_logic import BOE, CHICAGO, DRIVERS, EVENTS, HISTORY_TEXT, VALUE_TEXT
from .history import FIB_SOURCE, WB_URL, MIRROR_PAGE, choose_history, event_window, fibonacci, swings, trend_summary
from .yields_ui import rate_time

UP, DOWN, GOLD = '#FF5779', '#00E5AD', '#F4C76A'
APP_URL = 'https://github.com/lizongmeng638-afk/gold-intelligence/raw/refs/heads/main/downloads/GOLD_INTELLIGENCE_Mac.zip'


def layout(fig, height=410):
    fig.update_layout(template='plotly_dark', height=height, margin=dict(l=8,r=12,t=25,b=10),
                      paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                      yaxis_title='美元 / 金衡盎司', hovermode='x unified',
                      legend=dict(orientation='h',y=1.13,x=0))
    return fig


def history_chart(rows, events, logarithmic=True):
    fig = go.Figure(go.Scatter(x=[r['date'] for r in rows], y=[r['value'] for r in rows],
                              name='黄金月均价', line=dict(color=GOLD,width=2.2),
                              hovertemplate='%{x|%Y-%m} 月均价<br>$%{y:,.2f}<extra></extra>'))
    lookup = {r['date'][:7]:r['value'] for r in rows}
    marks = [e for e in events if e['date'][:7] in lookup]
    fig.add_trace(go.Scatter(x=[e['date'][:7]+'-01' for e in marks],
                            y=[lookup[e['date'][:7]] for e in marks], mode='markers',
                            name='已整理的历史事件', marker=dict(size=9,color='#66B7FF',symbol='diamond'),
                            customdata=[[e['date'],e['title']] for e in marks],
                            hovertemplate='%{customdata[0]}<br>%{customdata[1]}<br>当月均价 $%{y:,.2f}<extra></extra>'))
    fig.update_yaxes(type='log' if logarithmic else 'linear',tickformat=',.0f')
    if logarithmic:
        import math
        low,high=min(r['value'] for r in rows),max(r['value'] for r in rows)
        ticks=[m*10**n for n in range(math.floor(math.log10(low)),math.ceil(math.log10(high))+1) for m in (1,2,5) if low<=m*10**n<=high]
        fig.update_yaxes(tickmode='array',tickvals=ticks,ticktext=[f'{v:,.0f}' for v in ticks])
    fig.update_xaxes(rangeslider=dict(visible=True,thickness=.08))
    return layout(fig,450)


def annual_changes(rows):
    lookup={r['date'][:7]:r['value'] for r in rows}
    result=[]
    for year in sorted({r['date'][:4] for r in rows}):
        months=sorted(m for m in lookup if m.startswith(year))
        previous=f'{int(year)-1}-12'
        if previous in lookup:
            end=months[-1]
            result.append({'year':year if end.endswith('-12') else f'{year}至{end[-2:]}月',
                           'change':lookup[end]/lookup[previous]-1, 'start':previous,'end':end})
    return result


def fib_frame(info):
    return pd.DataFrame([{'类型':r['kind'],'比例':f"{r['ratio']:.1%}",
                          '参考价格（USD/oz）':r['value'],
                          '较最新基准价':r['value']/info['latest']['value']-1}
                         for r in info['levels']])


def render_fibonacci(feeds, history):
    st.markdown('### 04 / 斐波那契：把波段位置算清楚')
    daily=((feeds.get('market:GC=F') or {}).get('data') or {}).get('rows',[])
    options=['近期 COMEX 期货日线','长期黄金月均价'] if len(daily)>=2 else ['长期黄金月均价']
    basis=st.selectbox('技术分析数据口径',options,key='fib_basis')
    monthly=basis=='长期黄金月均价'
    window=st.selectbox('斐波那契观察范围', ['近60个月','近120个月','全部历史'] if monthly else ['近90个交易日','近250个交易日','近500个交易日'],index=0 if monthly else 1,key='fib_window_'+str(monthly))
    count={'近60个月':60,'近120个月':120,'全部历史':len(history['rows']),'近90个交易日':90,'近250个交易日':250,'近500个交易日':500}[window]
    rows=(history['rows'] if monthly else daily)[-count:]
    if len(rows)<2:
        st.info('有效价格不足，暂不能计算斐波那契。')
        return
    mode=st.radio('波段取点方式',['自动区间高低点','手动选择日期'],horizontal=True,key='fib_mode')
    start=end=None
    dates=[r['date'][:10] for r in rows]
    if mode=='手动选择日期':
        a,b=st.columns(2)
        start=a.selectbox('起点 A（较早日期）',dates,index=0,key='fib_a_'+str(monthly))
        candidates=[d for d in dates if d>start]
        if not candidates:
            st.warning('起点后没有其他日期，请选择更早的起点。')
            return
        end=b.selectbox('终点 B（较晚日期）',candidates,index=len(candidates)-1,key='fib_b_'+str(monthly))
    try:
        info=fibonacci(rows,start,end)
    except (ValueError,KeyError) as exc:
        st.info(str(exc))
        return
    a,b,c=st.columns(3)
    a.metric('波段起点 A',f"${info['a']['value']:,.2f}")
    a.caption(info['a']['date'])
    b.metric('波段终点 B',f"${info['b']['value']:,.2f}")
    b.caption(info['b']['date'])
    c.metric('最新日线基准' if not monthly else '最新月均基准',f"${info['latest']['value']:,.2f}")
    c.caption(info['latest']['date'][:7] if monthly else info['latest']['date'])
    st.caption(f"{info['direction']} · {basis} · 使用 {len(rows)} 个观测值。自动取点使用所选区间的最高/最低有效价格，再按时间先后确定方向；日线为收盘参考，非盘中高低点。")
    short,long,lookback=(6,12,3) if monthly else (20,50,5)
    trend=trend_summary(rows,short,long,lookback)
    if trend:
        unit='月' if monthly else '个交易日'
        st.markdown(f"**近期走势位置：{trend['label']}** · 最近{lookback}{unit}变化 {trend['change']:+.2%}（{trend['start']} → {trend['end']}）")
        st.caption(f"{short}期均价 ${trend['short_mean']:,.2f} · {long}期均价 ${trend['long_mean']:,.2f}。价格 > 短均线 > 长均线记为偏强，反向排列记为偏弱，其余记为震荡或转折；这是价格位置描述，不是涨跌预测。")
    last=pd.Timestamp(info['latest']['date'])
    if not monthly and (pd.Timestamp.now().normalize()-last).days>7:
        st.warning('期货日线已超过7天未更新；以下为历史位置，不能代表当前市场。')
    fig=go.Figure(go.Scatter(x=dates,y=[r['value'] for r in rows],name=basis,line=dict(color=GOLD,width=2)))
    for level in info['levels']:
        if level['value']<=0:
            continue
        color=GOLD if level['ratio']==.618 else '#66B7FF' if level['kind']=='延伸' else '#7586A3'
        fig.add_hline(y=level['value'],line_color=color,line_dash='dash',line_width=1,
                      annotation_text=f"{level['kind']} {level['ratio']:.1%} · {level['value']:,.2f}",annotation_position='top left')
    fig.add_trace(go.Scatter(x=[info['a']['date'],info['b']['date']],y=[info['a']['value'],info['b']['value']],
                            mode='markers+text',text=['A','B'],textposition='top center',name='计算锚点',marker=dict(size=11,color='#FFFFFF')))
    st.plotly_chart(layout(fig,510),width='stretch',key='fibonacci_chart')
    lower,upper=st.columns(2)
    lower.markdown(f"**↓ 下方最近观察位：{('$'+format(info['below']['value'],',.2f')) if info['below'] else '暂无正价格观察位'}**")
    upper.markdown(f"**↑ 上方最近观察位：{('$'+format(info['above']['value'],',.2f')) if info['above'] else '已超出当前计算范围'}**")
    if info['invalid']:
        st.warning('最新基准已经穿过波段起点 A，原波段结构已被破坏，应重新选点。')
    st.caption('这些价位是技术观察线，不是内在价值、必达目标、买入建议或上涨概率。突破后可能延续，也可能失败；需要后续价格和宏观因素验证。50%是常用中点，并非斐波那契数列比率。负价格延伸值不绘制。')
    with st.expander('查看全部价位、计算公式与下载'):
        frame=fib_frame(info)
        st.dataframe(frame.style.format({'参考价格（USD/oz）':'{:,.2f}','较最新基准价':'{:+.2%}'}),hide_index=True,width='stretch')
        st.markdown('回撤价 = B + (A − B) × 回撤比例；两点延伸价 = A + (B − A) × 延伸倍数。上涨与下跌波段使用同一公式。延伸使用127.2%、161.8%，不是三点投射。')
        st.markdown(f'[CME 技术分析说明]({FIB_SOURCE})')
        export=frame.copy()
        for name,value in [('数据口径',basis),('起点日期',info['a']['date']),('起点价格',info['a']['value']),('终点日期',info['b']['date']),('终点价格',info['b']['value']),('基准日期',info['latest']['date']),('基准价格',info['latest']['value'])]:
            export[name]=value
        st.download_button('下载本次斐波那契计算 CSV',export.to_csv(index=False).encode('utf-8-sig'),'gold_fibonacci.csv','text/csv',key='download_fib')


def render_logic(feeds):
    st.markdown('### 01 / 先理解黄金的定价逻辑')
    st.write(VALUE_TEXT)
    with st.expander('从黄金货币史到现代市场'):
        st.write(HISTORY_TEXT)
        st.markdown(f'[英格兰银行：黄金的价值与历史]({BOE}) · [美联储：布雷顿森林体系](https://www.federalreservehistory.org/essays/bretton-woods-created)')
    cols=st.columns(2)
    for i,driver in enumerate(DRIVERS):
        with cols[i%2]:
            st.markdown(f'<div class="card"><b>{escape(driver["name"])}</b><p>{escape(driver["path"])}</p><span class="small">验证：{escape(driver["check"])}</span><br><a href="{driver["url"]}" target="_blank" rel="noopener">研究来源 ↗</a></div>',unsafe_allow_html=True)
    st.caption('以上是分析框架与待验证的传导路径，作用强弱会变，不能把任何一个指标当成固定开关。')
    st.markdown('### 02 / 1971年至今：黄金怎样上涨与回落')
    feed=feeds.get('history:gold',{})
    history=choose_history(feed)
    all_rows=history['rows']
    cutoff=st.selectbox('长期走势范围',['1971年至今','近20年','近10年','近5年'],key='long_history_scope')
    years={'近20年':20,'近10年':10,'近5年':5}.get(cutoff)
    minimum=pd.Timestamp(all_rows[-1]['date'])-pd.DateOffset(years=years) if years else pd.Timestamp('1971-01-01')
    rows=[r for r in all_rows if pd.Timestamp(r['date'])>=minimum]
    events=[e for e in EVENTS if rows[0]['date'][:7]<=e['date'][:7]<=rows[-1]['date'][:7]]
    change=rows[-1]['value']/rows[0]['value']-1
    monthly_change=rows[-1]['value']/rows[-2]['value']-1 if len(rows)>1 else None
    a,b,c=st.columns(3)
    a.metric('最近完整月份的黄金均价',f"${rows[-1]['value']:,.2f}",f'{monthly_change:+.2%} 较上月' if monthly_change is not None else None,delta_color='inverse')
    a.caption(f"统计期：{rows[-1]['date'][:7]} · USD/oz")
    b.metric('所选区间月均价变化',f'{change:+.1%}')
    b.caption(f"{rows[0]['date'][:7]} → {rows[-1]['date'][:7]}；不含费用、通胀与汇率")
    c.metric('有效月度观测',str(len(rows)))
    c.caption(f'已整理事件 {len(events)} 个；蓝色菱形可查看')
    expected=(pd.Timestamp.now().to_period('M')-1).strftime('%Y-%m')
    cadence='正常月频，最新完整月已覆盖' if rows[-1]['date'][:7]>=expected else '月度资料待更新'
    origin='随包历史快照' if history.get('bundled') else '后台下载的公开镜像'
    st.caption(f"{origin} · {cadence} · 观测期 {history['observed_at'][:7]} · 月均价非实时行情。")
    if history.get('bundled'):
        st.caption(f"快照取得时间：{rate_time(history.get('snapshot_retrieved_at'))} 北京时间；后台更新失败时保留快照。")
    else:
        st.caption(f"最近采集时间：{rate_time(feed.get('fetched_at'))} 北京时间 · {feed.get('status','')}")
    logarithmic=st.checkbox('使用对数价格轴（便于比较不同时代的比例变化）',value=True,key='history_log')
    st.plotly_chart(history_chart(rows,events,logarithmic),width='stretch',key='long_history_chart')
    st.caption('蓝色节点按事件所属月份定位，纵坐标为当月均价，不代表事件当天成交价。主图拖动底部滑块只缩放图表；上方“长期走势范围”同时控制统计、事件和导出。')
    annual=annual_changes(rows)
    if annual:
        fig=go.Figure(go.Bar(x=[r['year'] for r in annual],y=[r['change']*100 for r in annual],
                            marker_color=[UP if r['change']>0 else DOWN if r['change']<0 else GOLD for r in annual],
                            hovertemplate='%{x}<br>%{y:+.2f}%<extra></extra>',name='月均价年度变化'))
        layout(fig,250).update_yaxes(title='变化 %')
        st.plotly_chart(fig,width='stretch',key='annual_gold_change')
        st.caption('红色↑上涨，绿色↓下降。计算为当年12月均价 / 上年12月均价 − 1；未完成年份用最近完整月份。缺少上年12月时不计算。')
    with st.expander('查看上涨、下跌阶段（按月均价复盘）'):
        threshold=st.selectbox('确认反转幅度',['20%','30%'],key='swing_threshold')
        legs=swings(rows,float(threshold[:-1])/100)
        phase_rows=[]
        for leg in legs:
            context=[e['title'] for e in events if leg['a']['date'][:7]<=e['date'][:7]<=leg['b']['date'][:7]]
            phase_rows.append({'阶段':'↑ 上涨' if leg['change']>0 else '↓ 下跌' if leg['change']<0 else '→ 持平',
                               '起始月':leg['a']['date'][:7],'结束月':leg['b']['date'][:7],
                               '起始均价':leg['a']['value'],'结束均价':leg['b']['value'],'幅度':leg['change'],
                               '状态':'已确认的历史阶段' if leg['confirmed'] else '进行中，尚未反转确认',
                               '区间内已整理事件':'；'.join(context) or '本版尚未整理该区间事件'})
        if phase_rows:
            frame=pd.DataFrame(phase_rows)
            styled=frame.style.format({'起始均价':'{:,.2f}','结束均价':'{:,.2f}','幅度':'{:+.1%}'}).map(lambda v:f'color:{UP if v>0 else DOWN if v<0 else GOLD};font-weight:bold',subset=['幅度'])
            st.dataframe(styled,hide_index=True,width='stretch')
        st.caption(f'价格反向变动达到{threshold}后确认前一个月度极值。拐点是事后识别，最后一段未确认；不是当时可获得的交易信号。区间内事件仅为背景，不代表已经证明因果。')
    st.markdown('### 03 / 关键事件：事实、传导路径与反证')
    st.caption(f'当前范围已整理 {len(events)} 个节点，属于精选历史复盘，覆盖至2025年2月；最新动态见“国际新闻”。事件前后涨跌不能直接归因于该事件。')
    if not events:
        st.info('所选范围没有已整理的历史事件，请扩大范围或查看国际新闻。')
    else:
        selected=st.selectbox('选择一个历史节点',events,format_func=lambda e:e['date']+' · '+e['title'],key='gold_event')
        with st.container(border=True):
            st.markdown(f"**已核验事实**　{selected['fact']}")
            st.write('可能的传导路径：'+selected['path'])
            st.write('相反力量：'+selected['counter'])
            st.write('如何验证：'+selected['check'])
            window=event_window(rows,selected['date'])
            if window:
                st.markdown(f"**窗口内实际月均价变化：{window['change']:+.2%}**　{window['a']['date'][:7]}（${window['a']['value']:,.2f}）→ {window['b']['date'][:7]}（${window['b']['value']:,.2f}）")
            else:
                st.caption('当前筛选范围未完整覆盖观察窗口，不计算涨跌。')
            st.caption('窗口定义：事件前一个月，到事件所属月之后第3个月；包含其他事件和预期交易，不能解释为该事件造成的收益。')
            st.markdown(f"[{selected['source']}：查看原始资料 ↗]({selected['url']})")
        with st.expander('展开当前范围的全部事件清单'):
            st.dataframe(pd.DataFrame([{'日期':e['date'],'节点':e['title'],'类别':e['category'],'已核验事实':e['fact'],'来源':e['url']} for e in events]),hide_index=True,width='stretch',column_config={'来源':st.column_config.LinkColumn('原始资料')})
    render_fibonacci(feeds,history)
    st.markdown('### 05 / 按这条顺序形成判断')
    st.write('先看价格口径与更新时间 → 看实际利率、美元及风险环境 → 核对事件的事实与相反力量 → 用价格走势验证 → 再用技术价位描述位置和失效条件。技术价位不能替代基本面，也不自动产生可靠概率。')
    a,b=st.columns(2)
    a.link_button('下载 Mac 应用 ZIP',APP_URL,width='stretch')
    b.download_button('下载当前范围月均价 CSV',pd.DataFrame(rows).rename(columns={'date':'统计月首日标记','value':'黄金月均价_USD每金衡盎司'}).to_csv(index=False).encode('utf-8-sig'),'gold_monthly_history.csv','text/csv',width='stretch',key='download_history')
    st.caption('Mac 桌面版支持 Apple 芯片及 Intel（macOS 12及以上）；实时分析需要联网，随包历史资料可离线查看。无需安装 Python。')
    with st.expander('数据来源、原始记录与计算口径'):
        st.write(history['basis_note'])
        st.markdown(f'[世界银行原始发布页]({WB_URL}) · [公开镜像与许可]({MIRROR_PAGE})')
        st.write('当前连接使用第三方公开镜像；不冒充世界银行实时接口。原始月度序列不与近期 GC=F 期货日线拼接。')
        if history.get('snapshot_note'):
            st.write(history['snapshot_note'])
            st.markdown(f"[世界银行抽样核对月报]({history['verification_url']})")
        preview=pd.DataFrame(rows[:3]+rows[-3:])
        st.dataframe(preview,hide_index=True,width='stretch')
        st.download_button('下载当前范围事件与来源 JSON',json.dumps(events,ensure_ascii=False,indent=2),'gold_events.json','application/json',key='download_events')
