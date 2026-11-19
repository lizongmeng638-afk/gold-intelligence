from datetime import datetime
from html import escape
import json
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .domestic import BANKS, LOW, HIGH, MID, comparable

TZ = ZoneInfo('Asia/Shanghai')


def price_card(label, row, color):
    if row is None:
        return
    st.markdown(f'''<div style="border:2px solid {color};border-radius:14px;padding:16px;background:#142039">
<span style="color:{color};font-weight:800">{escape(label)}</span><br>
<strong style="color:{color};font-size:30px">¥{row['price']:,.2f}</strong> <span>元/克</span><br>
<span>{escape(row['channel'])} · {escape(row['product'])}</span></div>''', unsafe_allow_html=True)


def render_comparison(rows, key):
    if not rows:
        st.info('尚无可比报价。没有有效价格的渠道不会参与排名。')
        return
    groups = sorted({(r['category'], r['purity']) for r in rows})
    default = next((i for i,g in enumerate(groups) if g==('品牌金饰','成色未注明')), 0)
    group = st.selectbox('比较口径', groups, index=default, format_func=lambda g:f'{g[0]} · {g[1]}', key=key+'_group')
    candidates = [r for r in rows if (r['category'],r['purity'])==group]
    sides = sorted({r['side'] for r in candidates})
    side = st.radio('客户交易方向', sides, horizontal=True, key=key+'_side')
    candidates = [r for r in candidates if r['side']==side]
    dates = sorted({r['date'] for r in candidates}, reverse=True)
    date = st.selectbox('同一报价日期', dates, key=key+'_date')
    source_kind = candidates[0]['source_kind']
    selected = comparable(rows,*group,date,side,source_kind)
    if date != str(datetime.now(TZ).date()):
        st.warning(f'当前比较的是 {date} 的历史报价，不代表今日价格。')
    if not selected:
        st.info('该日期暂无同口径报价。')
        return
    st.caption('颜色表示本组数值高低：🟢 鲜绿＝最低价　🔴 亮红＝最高价　🟡 金黄＝中间价/同价。价格高低不代表买卖建议。')
    a,b,c = st.columns([1,1,1])
    with a:
        price_card(('最低挂牌价' if selected[0]['price']!=selected[-1]['price'] else '同价参考') if len(selected)>1 else '当前参考价',selected[0],LOW if len(selected)>1 and selected[0]['price']!=selected[-1]['price'] else MID)
    with b:
        price_card('最高挂牌价' if len(selected)>1 else '暂无第二条可比报价',selected[-1] if len(selected)>1 else None,HIGH if selected[0]['price']!=selected[-1]['price'] else MID)
    c.metric('组内价差',f"¥{selected[-1]['price']-selected[0]['price']:,.2f}/克")
    c.caption(f'{len(selected)} 条报价 · {len({r["channel"] for r in selected})} 个渠道 · {date}')
    chart = go.Figure(go.Bar(x=[r['price'] for r in selected],
        y=[r['channel']+' · '+r['product'] for r in selected],orientation='h',
        marker_color=[r['color'] for r in selected],
        text=[f"¥{r['price']:,.2f}　{r['marker']}" for r in selected],textposition='auto',
        customdata=[[r['marker'],r['date']] for r in selected],
        hovertemplate='%{y}<br>¥%{x:.2f}/克<br>%{customdata[0]} · %{customdata[1]}<extra></extra>'))
    chart.update_layout(template='plotly_dark',height=max(280,len(selected)*42+70),
        yaxis=dict(autorange='reversed'),xaxis_title='人民币元/克',margin=dict(l=5,r=10,t=15,b=30),
        paper_bgcolor='rgba(0,0,0,0)',plot_bgcolor='rgba(0,0,0,0)')
    st.plotly_chart(chart,width='stretch',key=key+'_bars')
    display = pd.DataFrame([{'渠道':r['channel'],'产品':r['product'],'价格（元/克）':r['price'],
        '高低标记':r['marker'],'比最低价贵（元/克）':r['difference'],'报价日期':r['date'],
        '费用口径':r['fees'],'来源':r['source'],'原始链接':r.get('url','')} for r in selected])
    colors = [r['color'] for r in selected]
    def style_row(row):
        styles = ['']*len(row)
        i = row.name
        for col in ['价格（元/克）','高低标记']:
            styles[row.index.get_loc(col)]=f'background-color:{colors[i]};color:#08121c;font-weight:800'
        return styles
    st.dataframe(display.style.apply(style_row,axis=1).format({'价格（元/克）':'{:.2f}','比最低价贵（元/克）':'{:.2f}'}),
        width='stretch',hide_index=True,column_config={'原始链接':st.column_config.LinkColumn('原始链接')})
    st.download_button('下载当前比价表 CSV',display.to_csv(index=False).encode('utf-8-sig'),
                       file_name=f'黄金渠道比价_{date}.csv',mime='text/csv',key=key+'_csv')
    excluded = [r for r in rows if (r['category'],r['purity'])==group and r['side']==side and r['date']!=date]
    if excluded:
        with st.expander(f'{len(excluded)} 条其他日期报价（未参与当前高低价排名）'):
            st.dataframe(pd.DataFrame(excluded)[['channel','product','price','date']],hide_index=True,width='stretch')


def render_banks():
    st.caption('银行积存金通常有客户买入价和赎回价。目前尚未接入各银行的实时接口；下面的报价由你录入，单独比较，不混入公开挂牌价。')
    manual = st.session_state.setdefault('domestic_manual_quotes',[])
    coverage = [{'银行':bank,'报价接入':'本次会话已有手动记录' if any(r['channel']==bank for r in manual) else '未接入公开报价 · 待录入'} for bank in BANKS]
    st.dataframe(pd.DataFrame(coverage),hide_index=True,width='stretch')
    with st.expander('录入银行或其他渠道报价',expanded=not manual):
        with st.form('domestic_bank_form',clear_on_submit=False):
            a,b=st.columns(2)
            bank=a.selectbox('银行/渠道',BANKS+['其他渠道'])
            custom=a.text_input('其他渠道名称（仅选择其他渠道时填写）')
            category=b.selectbox('产品类别',['银行积存金','投资黄金/金条','品牌金饰','回收参考价'])
            product=a.text_input('具体产品名称',value='黄金积存')
            purity=b.selectbox('报价注明成色',['成色未注明','999足金','9999及以上（按原产品名核实）'])
            side=a.selectbox('客户买卖方向',['买入','卖出'])
            price=b.number_input('报价（元/克）',min_value=0.01,value=None,step=.01,placeholder='请输入实际看到的价格')
            now=datetime.now(TZ)
            date=a.date_input('报价日期',value=now.date(),max_value=now.date())
            quoted_time=b.time_input('报价时间（北京时间）',value=now.time().replace(microsecond=0))
            fees=st.text_input('费用说明',value='手续费/工费未确认，仅比较基础报价')
            submit=st.form_submit_button('加入本次会话比价')
        if submit:
            channel=custom.strip() if bank=='其他渠道' else bank
            at=datetime.combine(date,quoted_time,tzinfo=TZ)
            if not channel or not product.strip() or price is None:
                st.error('请填写渠道、产品和真实报价。')
            elif at>datetime.now(TZ):
                st.error('报价时间不能是未来时间。')
            else:
                row={'channel':channel,'product':product.strip(),'category':category,'purity':purity,
                    'side':side,'price':price,'date':str(date),'quoted_at':at.isoformat(),
                    'source':'手动录入（未核验）','source_kind':'手动录入','url':'','fees':fees}
                manual[:]=[r for r in manual if (r['channel'],r['product'],r['side'],r['date'])!=(channel,row['product'],side,str(date))]
                manual.append(row)
                st.success('已加入。银行报价只比较同日、同方向、同成色且距组内最新报价15分钟内的记录。')
    render_comparison(manual,'bank_quotes')
    if manual:
        st.download_button('导出本次手动记录 JSON',json.dumps(manual,ensure_ascii=False,indent=2),
                           file_name='手动黄金报价.json',mime='application/json')
        st.caption('手动记录保存在本次浏览器会话中；关闭会话后可能丢失，可先导出。')


def render_domestic(feeds):
    st.markdown('### 国内金价 · 走势与渠道比价')
    st.caption('人民币元/克 · 国内走势来自上金所 Au99.99 日收盘价，品牌挂牌价来自 SMM 汇总；银行报价单独管理。')
    history=feeds.get('cn:history',{})
    retail=feeds.get('cn:retail',{})
    hdata=history.get('data') or {}
    rows=hdata.get('rows',[])
    st.markdown('#### 国内黄金走势')
    if rows:
        prices=pd.DataFrame(rows)
        a,b,c=st.columns(3)
        latest=rows[-1]
        change=latest['value']-rows[-2]['value'] if len(rows)>1 else None
        a.metric('Au99.99 最新日收盘',f"¥{latest['value']:,.2f}/克",f'{change:+.2f}/克' if change is not None else None)
        b.metric('展示区间最低收盘',f"¥{prices['value'].min():,.2f}/克")
        c.metric('展示区间最高收盘',f"¥{prices['value'].max():,.2f}/克")
        fig=go.Figure(go.Scatter(x=prices['date'],y=prices['value'],mode='lines+markers',
            name='Au99.99 日收盘',line=dict(color=MID,width=3),fill='tozeroy',fillcolor='rgba(245,200,76,.08)'))
        for label,color,value in [('区间最低',LOW,prices['value'].min()),('区间最高',HIGH,prices['value'].max())]:
            subset=prices[prices['value']==value]
            fig.add_trace(go.Scatter(x=subset['date'],y=subset['value'],mode='markers',name=label,
                marker=dict(color=color,size=13,line=dict(color='#ffffff',width=1))))
        fig.update_layout(template='plotly_dark',height=330,yaxis=dict(title='人民币元/克',rangemode='normal'),
            xaxis_title='交易日期',paper_bgcolor='rgba(0,0,0,0)',plot_bgcolor='rgba(0,0,0,0)',
            margin=dict(l=5,r=10,t=15,b=30),hovermode='x unified')
        # Do not include zero in the price range solely because the line is filled.
        fig.update_yaxes(range=[prices['value'].min()*.98,prices['value'].max()*1.02])
        st.plotly_chart(fig,width='stretch',key='domestic_history_chart')
        st.caption(f"来源：上海黄金交易所 · 最近30个自然日内的已公布日线 · 最后观测日 {latest['date']} · {history.get('status','')}")
        st.link_button('查看上金所原始行情',hdata['url'])
    else:
        st.info('上金所日线正在采集或暂未取得；不会用国际金价换算来冒充国内交易价格。')
    if history.get('error'):
        st.warning(f"国内走势更新失败：{history['error']}；已有成功缓存继续显示。")
    store_tab,bank_tab=st.tabs(['品牌与金条渠道','银行积存金 / 自选渠道'])
    with store_tab:
        st.markdown('#### 同类产品价格对比')
        st.caption('基础挂牌价可能不含工费，成色、地区、优惠和最终成交价须向渠道核实。高低标记仅在本次选定的类别、成色、日期和买卖方向内计算，不代表全市场最优价。')
        data=retail.get('data') or {}
        render_comparison(data.get('quotes',[]),'retail_quotes')
        if retail.get('error'):
            st.warning(f"挂牌价更新失败：{retail['error']}；展示的缓存日期可在表中查看。")
        st.link_button('查看 SMM 原始挂牌表','https://precious.smm.cn/gold-price')
    with bank_tab:
        render_banks()
