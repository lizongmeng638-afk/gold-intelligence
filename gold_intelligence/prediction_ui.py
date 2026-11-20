from html import escape

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .intelligence import CHICAGO, GRAM, factor_conclusion, local_stamp, model_groups

COLORS={'bullish':'#FF5779','bearish':'#00E5AD','mixed':'#F4C76A','unknown':'#FFB84D'}


def render_factor_focus(factors):
    st.markdown('### 重要因子提醒')
    st.caption('优先看实际收益率和美元，再看风险与通胀传导。优先级是阅读顺序，不是固定的影响权重。')
    columns=st.columns(2)
    for column,factor in zip(columns,factors[:2]):
        color='#FFB84D' if not factor['timely'] else '#FF5779' if factor['signal']>0 else '#00E5AD' if factor['signal']<0 else '#F4C76A'
        with column:
            st.markdown(f'''<div class="factor-focus" style="border-color:{color}"><div class="factor-priority">优先关注 · {escape(factor['name'])}</div>
<div class="factor-value">{escape(factor['value'])}</div><b style="color:{color}">{escape(factor['change'])} · 黄金影响：{escape(factor['effect'])}</b>
<p>{escape(factor['explanation'])}</p><div class="small">观测日：{escape(factor['date'])} · {escape(factor.get('verification','待核验'))}<br>{escape(factor['verify'])}</div></div>''',unsafe_allow_html=True)
    with st.expander('其他因子、提醒阈值和研究依据'):
        for factor in factors[2:]:
            st.markdown(f"**{factor['name']}**　{factor['value']} · {factor['change']} · {factor['effect']}")
            st.caption(f"观测日 {factor['date']}；{factor['explanation']} {factor['verify']}")
        st.caption('提醒筛选阈值：美元5期变化超过±0.25%；实际收益率超过±5基点；VIX超过±8%。样本不足6个时注明无法计算5期变化。这些阈值未作事件影响幅度回测，不对应固定金价涨跌幅。颜色表示对黄金的方向假设：红色偏多、绿色偏空、黄色待确认。')
        st.markdown(f'[芝加哥联储：黄金价格驱动研究]({CHICAGO}) · [世界黄金协会：驱动因素会随时期变化]({GRAM})')


def prediction_table(forecast):
    frame=pd.DataFrame(forecast['rows'])
    return frame[['name','date','center','low80','high80','low95','high95','up','flat','down']].rename(columns={
        'name':'周期（交易日）','date':'目标日期参考','center':'中心情景价','low80':'理论80%下沿','high80':'理论80%上沿',
        'low95':'理论95%下沿','high95':'理论95%上沿','up':'上涨情景概率','flat':'震荡情景概率','down':'下跌情景概率'})


def render_prediction_center(market,feeds,readiness,forecast,factors):
    st.markdown('### 未来黄金走势预测')
    summary=factor_conclusion(factors)
    color=COLORS[summary['kind']]
    key_values=' · '.join(f"{f['name']} {f['value']}（{f['change']}；{f['date']}）" for f in factors[:2])
    st.markdown(f'<div class="priority-alert" style="border-color:{color}" title="{escape(summary["text"],quote=True)}"><b style="color:{color}">{escape(summary["label"])}</b><div class="small">{escape(key_values)}</div></div>',unsafe_allow_html=True)
    if not readiness['ready']:
        st.warning(readiness['message'])
        st.caption(readiness['schedule']+'；数据就绪后自动尝试生成，无法保证免费来源何时返回新数据。')
        render_factor_focus(factors)
        return
    if not forecast:
        st.warning('价格历史已取得，但有效训练样本或近期因子不足，暂未生成预测。')
        st.caption(readiness['schedule']+'；至少需要60条完整训练记录，因子日期不能落后价格超过7天。不会用示例预测填补空缺。')
        render_factor_focus(factors)
        return
    st.caption(f"可立即查看 · 本次生成：{local_stamp(forecast.get('generated_at'))} 北京时间 · 价格基准日：{readiness['reference_date']} · 因子日：{forecast['feature_date']}")
    st.caption(readiness['schedule']+'；取得新有效数据后重新计算，检查不保证来源发布。')
    options={1:'1个交易日',3:'3个交易日',7:'7个交易日',30:'30个交易日',90:'90个交易日'}
    horizon=st.radio('预测周期',list(options),index=2,format_func=options.get,horizontal=True,key='forecast_horizon')
    selected=next(r for r in forecast['rows'] if r['h']==horizon)
    st.markdown(f"**{options[horizon]} · 目标日期参考 {selected['date'].date()}**")
    a,b,c=st.columns([1,1.2,1.2])
    a.metric('中心情景价',f"${selected['center']:,.2f}",f"{selected['center']/readiness['reference']-1:+.2%} 较基准",delta_color='inverse')
    b.metric('理论80%情景区间',f"{selected['low80']:,.0f}–{selected['high80']:,.0f}")
    c.metric('理论95%情景区间',f"{selected['low95']:,.0f}–{selected['high95']:,.0f}")
    st.markdown(f"<div class='scenario-row'><span style='color:#FF7893'>↑ 上涨 {selected['up']:.1%}</span><span style='color:#F4C76A'>→ 震荡 {selected['flat']:.1%}</span><span style='color:#00E5AD'>↓ 下跌 {selected['down']:.1%}</span></div>",unsafe_allow_html=True)
    st.caption(f"单位：美元/金衡盎司，GC=F期货日线基准 ${readiness['reference']:,.2f}，不是现货或人民币金价。概率来自模型分布假设，80%/95%区间尚未经过各周期覆盖率校准。交易日日期只排除周末，未纳入交易所节假日。")
    st.caption('预测及美元/VIX/原油提醒按纽约17:00作日线完成筛选；此前剔除当日参考值，不能当作官方结算确认。1个交易日不等于自然24小时，盘中报价另见下方行情。')
    acc,baseline=forecast.get('acc'),forecast.get('baseline_acc')
    if acc is None:
        st.warning('当前为历史统计基线，缺少有效的留出集准确率，不能给出已验证胜率。')
    elif baseline is not None:
        comparison='未优于' if acc<=baseline else '高于'
        st.info(f"有效性提示：日线留出集方向准确率 {acc:.1%}，{comparison}同区间简单基准 {baseline:.1%}（{forecast['validation_count']}条）。单次留出结果不是各预测周期的胜率，模型仍属探索性统计估计。")
    if str(forecast['feature_date'])<readiness['reference_date']:
        st.warning('部分因子日期落后黄金价格基准日，当前情景需要特别关注因子更新。')
    render_factor_focus(factors)
    with st.expander('查看预测曲线、全部周期与下载',expanded=True):
        gold=market['Gold'].dropna().tail(90)
        dates=[gold.index[-1]]+[r['date'] for r in forecast['rows']]
        base=readiness['reference']
        fig=go.Figure(go.Scatter(x=gold.index,y=gold.values,name='GC=F历史日线',line=dict(color='#F4C76A')))
        fig.add_trace(go.Scatter(x=dates,y=[base]+[r['high80'] for r in forecast['rows']],line=dict(width=0),showlegend=False,hoverinfo='skip'))
        fig.add_trace(go.Scatter(x=dates,y=[base]+[r['low80'] for r in forecast['rows']],fill='tonexty',fillcolor='rgba(102,183,255,.14)',line=dict(width=0),name='理论80%情景区间（未校准）'))
        fig.add_trace(go.Scatter(x=dates,y=[base]+[r['center'] for r in forecast['rows']],mode='lines+markers',name='中心情景',line=dict(color='#66B7FF',dash='dash')))
        fig.update_layout(template='plotly_dark',height=340,margin=dict(l=5,r=8,t=35,b=5),legend=dict(orientation='h',y=1.16),
                          paper_bgcolor='rgba(0,0,0,0)',plot_bgcolor='rgba(0,0,0,0)',yaxis_title='美元 / 金衡盎司',hovermode='x unified')
        st.plotly_chart(fig,width='stretch',key='forecast_center_chart')
        table=prediction_table(forecast)
        price_columns=['中心情景价','理论80%下沿','理论80%上沿','理论95%下沿','理论95%上沿']
        formats={k:'{:,.2f}' for k in price_columns}
        formats.update({k:'{:.1%}' for k in ['上涨情景概率','震荡情景概率','下跌情景概率']})
        st.dataframe(table.style.format(formats),hide_index=True,width='stretch')
        st.caption('上涨/下跌情景以终点对基准价的收益超过±0.35倍该周期估计波动为界，中间为震荡；这些边界随周期变化，不是“收盘比现在高”的直接概率。简单基准始终预测训练集里更多出现的方向，再在相同留出集评估。')
        st.caption(f"训练记录 {forecast['training_count']}条 · 模型实际使用：{'、'.join(model_groups(forecast)) or '历史价格统计'}。实际利率历史不足时不会冒充已进入模型；监测卡片与模型输入是不同用途。")
        st.caption(forecast['note'])
        st.markdown('[CME 黄金期货合约与交易时段](https://www.cmegroup.com/markets/metals/precious/gold-futures.contractSpecs.html)')
        export=table.copy()
        export['生成时间_UTC']=forecast.get('generated_at')
        export['期货价格基准日']=readiness['reference_date']
        export['期货价格基准']=base
        export['因子日期']=forecast['feature_date']
        export['价格口径']='GC=F期货日线 USD/troy oz'
        export['概率性质']='分布假设下的情景概率，非已验证胜率'
        st.download_button('下载本次全部预测 CSV',export.to_csv(index=False).encode('utf-8-sig'),'gold_forecast.csv','text/csv',key='forecast_download')
