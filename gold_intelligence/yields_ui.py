from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .yields import RATE_LABELS, rate_summary, resolve_rates

TZ=ZoneInfo('Asia/Shanghai')


def render_rate_card(rows,label,compact=False):
    info=rate_summary(rows)
    if info is None:
        st.metric(label,'暂无')
        st.caption('独立收益率数据正在采集；若失败可查看数据诊断。')
        return
    bp=info['change_bp']
    st.metric(label,f"{info['value']:.2f}%",f'{bp:+.1f} 基点' if bp is not None else None,delta_color='inverse')
    color='#FF4F76' if bp is not None and bp>0 else '#00E5A8' if bp is not None and bp<0 else '#F5C84C'
    arrow='↑' if bp is not None and bp>0 else '↓' if bp is not None and bp<0 else '→'
    previous=f"较 {info['previous_date']}" if info['previous_date'] else '仅一个有效观测值'
    st.markdown(f'<span style="color:{color};font-weight:700">{arrow} {info["direction"]}</span> <span style="font-size:12px">{escape(previous)}</span>',unsafe_allow_html=True)
    st.caption(f"观测日：{info['date']}")
    if not compact:
        st.caption(f"最新观测来源：{info.get('source','FRED')}")
        if info['change5_bp'] is not None:
            st.caption(f"较前5个有效观测值：{info['change5_bp']:+.1f} 基点")
        else:
            st.caption('不足6个有效观测值，暂无5期变化。')
    if (datetime.now(TZ).date()-datetime.strptime(info['date'],'%Y-%m-%d').date()).days>7:
        st.warning('该观测日期已超过7天，请核对来源更新时间。')


def render_yields(feeds):
    rates=resolve_rates(feeds)
    st.markdown('### 美债收益率 · 上升与下降')
    st.caption('↑ 红色＝收益率上升；↓ 绿色＝下降；→ 金色＝持平。变化相对上一有效观测日，单位为基点；1基点=0.01个百分点。官方日度数据不是盘中实时报价。')
    columns=st.columns(3)
    for col,sid in zip(columns,['DFII10','DGS2','DGS10']):
        with col:
            render_rate_card(rates[sid],RATE_LABELS[sid])
    st.caption('10年期实际收益率来自通胀保值国债（TIPS）；2年期和10年期名义收益率未扣除通胀。不会用名义收益率替代实际收益率。')
    available=[sid for sid in RATE_LABELS if rates[sid]]
    if not available:
        st.info('独立FRED单项与美联储H.15备用来源均暂无有效值，正在后台按退避策略重试。')
        return
    chosen=st.multiselect('选择收益率曲线',available,default=[sid for sid in ['DFII10','DGS2'] if sid in available],
                         format_func=lambda sid:RATE_LABELS[sid],key='yield_curves')
    window=st.selectbox('走势图范围',['最近30个有效观测值','最近90个有效观测值','全部已取得数据'],key='yield_window')
    n=30 if window.startswith('最近30') else 90 if window.startswith('最近90') else None
    palette={'DFII10':'#F5C84C','DGS2':'#52C7FF','DGS10':'#C89BFF'}
    if chosen:
        fig=go.Figure()
        for sid in chosen:
            rows=rates[sid][-n:] if n else rates[sid]
            fig.add_trace(go.Scatter(x=[r['date'] for r in rows],y=[r['value'] for r in rows],
                mode='lines+markers',name=RATE_LABELS[sid],line=dict(color=palette[sid],width=2),
                hovertemplate='%{x}<br>%{y:.2f}%<extra>%{fullData.name}</extra>'))
        fig.update_layout(template='plotly_dark',height=340,yaxis_title='年化收益率（%）',xaxis_title='观测日期',
            hovermode='x unified',margin=dict(l=5,r=10,t=15,b=30),paper_bgcolor='rgba(0,0,0,0)',plot_bgcolor='rgba(0,0,0,0)')
        st.plotly_chart(fig,width='stretch',key='yield_history_plot')
        st.caption('曲线只画已取得的实际观测值，备用来源可能只有最近数日。不会补齐虚构历史，也不会用0填充假期或缺失数据。')
    details=[]
    for sid in available:
        summary=rate_summary(rates[sid])
        details.append({'指标':RATE_LABELS[sid],'最新值（%）':summary['value'],'方向':summary['direction'],
            '较上一观测日（基点）':summary['change_bp'],'上一有效观测日':summary['previous_date'],
            '最新观测日':summary['date'],'较前5个观测值（基点）':summary['change5_bp'],
            '有效观测数':summary['count'],'最新值来源':summary.get('source','FRED')})
    st.dataframe(pd.DataFrame(details),hide_index=True,width='stretch',
        column_config={'最新值（%）':st.column_config.NumberColumn(format='%.2f'),
                       '较上一观测日（基点）':st.column_config.NumberColumn(format='%+.1f'),
                       '较前5个观测值（基点）':st.column_config.NumberColumn(format='%+.1f')})
    for sid in available:
        info=rate_summary(rates[sid])
        st.markdown(f"[{RATE_LABELS[sid]} · 查看最新观测来源]({info.get('url','https://fred.stlouisfed.org/')})")
