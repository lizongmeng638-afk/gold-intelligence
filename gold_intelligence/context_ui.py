from html import escape
import math

import pandas as pd
import streamlit as st

from .activity import activity_assessment
from .event_analysis import stress_range
from .intelligence import local_stamp
from .speeches import SOURCES,message_time
from .yields import resolve_rates,rate_summary


def render_activity(context):
    st.markdown('### 美国PPI / PMI：增长与通胀分开看')
    metrics=context['activity']
    columns=st.columns(3)
    for col,kind,name in zip(columns,('ppi','manufacturing','services'),('最终需求PPI','ISM制造业PMI','ISM服务业PMI')):
        data=metrics[kind];assessment=activity_assessment(data,kind)
        with col:
            if kind=='ppi':
                col.metric(name+' · 季调环比',f"{data['mom']:+.1f}%" if data.get('mom') is not None else '暂无')
                col.caption(f"未季调同比：{data['yoy']:+.1f}%" if data.get('yoy') is not None else '同比样本不足')
                if data.get('previous_mom') is not None:col.caption(f"上期环比：{data['previous_mom']:+.1f}%")
            else:
                delta=data['value']-data['previous'] if data.get('previous') is not None else None
                col.metric(name,f"{data['value']:.1f}",f'{delta:+.1f} 点较上月' if delta is not None else None,delta_color='off')
            color='#FFB84D' if kind=='ppi' else '#66B7FF' if data['value']>50 else '#FFB84D'
            col.markdown(f'<div style="border-left:4px solid {color};padding:8px 12px;color:{color};font-size:18px;font-weight:700">{escape(assessment["label"])}</div>',unsafe_allow_html=True)
            col.caption(f"统计期：{data['period']} · {data['source']}")
            if data.get('snapshot'):
                col.warning('已核对的官方快照；本轮未能核验新发布。')
                col.caption('快照核验：'+local_stamp(data.get('verified_at'))+' 北京时间')
            else:col.caption('本轮来源检查：'+local_stamp(data.get('last_checked'))+' 北京时间')
            if data.get('connection_error'):col.caption('连接状态：'+data['connection_error'])
            col.markdown(f"[官方来源 ↗]({data['url']})")
    st.caption('未接入可靠的市场一致预期，暂不判断“超预期”。PMI高于50表示对应行业环比扩张，不是GDP增速；PPI上涨衡量生产端价格，不等于经济增长更强。PPI也不是美联储2%目标的直接口径。')
    with st.expander('数据怎样传导到黄金'):
        for kind,title in [('ppi','PPI'),('manufacturing','制造业PMI'),('services','服务业PMI')]:
            result=activity_assessment(metrics[kind],kind)
            st.markdown(f"**{title}**：{result['meaning']}\n\n传导假设：{result['path']}")
        st.caption('这些最新月度指标用于解释与观察；本版没有把单个月PPI/PMI快照伪装成长历史模型特征。')


def render_policy_energy(context):
    st.markdown('### 加息预期与能源：关注相反力量')
    rate=rate_summary(resolve_rates(context['feeds']).get('DGS2',[]))
    if rate:
        change=rate.get('change5_bp')
        text=f"近5个有效观测值 {change:+.1f} 基点" if change is not None else '不足6个有效观测值'
        st.markdown(f"**2年期名义美债收益率：{rate['value']:.2f}%** · {text} · 观测日 {rate['date']}")
    else:st.info('2年期收益率尚未取得，不把缺失填成“加息预期不变”。')
    st.caption('短端收益率只是利率预期的代理，也受期限与流动性溢价影响。本版未接入CME授权的FedWatch概率数据，不把2年期收益率或鹰鸽讲话条数换算成加息概率。')
    st.markdown('[CME FedWatch原始工具及方法](https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool)')
    cols=st.columns(3)
    for col,key,label,unit in zip(cols,('WTI','Brent','NaturalGas'),('WTI原油','Brent原油','美国天然气期货'),('USD/桶','USD/桶','USD/MMBtu')):
        series=context['market'][key].dropna() if key in context['market'] else pd.Series(dtype=float)
        series=series[series.map(math.isfinite)]
        change=float(series.iloc[-1]/series.iloc[-6]-1) if len(series)>=6 and series.iloc[-6]>0 else None
        col.metric(label,f'{series.iloc[-1]:,.2f}' if len(series) else '暂无',f'{change:+.2%} 较5期前' if change is not None else None,delta_color='off')
        col.caption(unit+(' · '+str(series.index[-1].date()) if len(series) else ''))
    st.info('能源上涨可以带来保值与避险需求，也可能强化加息预期；地缘动荡还可能引发现金需求和黄金抛售。先区分冲击渠道，再看美元、实际收益率及金价是否验证。')


def render_refresh_comparison(context):
    st.markdown('### 本次刷新与之前相比')
    state=context.get('journal_state')
    if not state or not state.get('current'):
        st.info('正在建立首个完整对照快照；消息和行情先显示，不用虚构历史预测填补。')
        return
    current=state['current'];previous=state.get('previous');diff=state['diff']
    st.caption(f"已保存快照 #{current['id']}：{local_stamp(current['captured_at'])} 北京时间。快照保存时间不是消息发生或模型生成时间。")
    if state['pending']:st.info('本轮数据仍在采集或等待合并；下面是最近一次已保存快照，不冒充当前全部来源已更新。')
    elif not state['wrote']:st.caption('当前数据与最近快照一致，未重复保存；下方对照最近两次有变化的快照。')
    if diff['first']:st.write(diff['message'])
    else:
        a,b,c=st.columns(3)
        a.metric('新收录消息',len(diff['new']))
        b.metric('标题/正文识别修订',len(diff['revised']))
        c.metric('上一快照',f"#{previous['id']}")
        st.caption('新收录不等于刚发生；按来源发布时间与首次收录分开理解。重复抓到同一消息不会增加条数。')
        if diff['range_changes']:
            table=[]
            for r in diff['range_changes']:
                table.append({'周期':f"{r['h']}个交易日",'上次目标日':r['previous_target'],'本次目标日':r['target'],
                              '上次中心价':r['previous_center'],'本次中心价':r['center'],
                              '上次80%区间':f"{r['previous_low80']:,.0f}–{r['previous_high80']:,.0f}",
                              '本次80%区间':f"{r['low80']:,.0f}–{r['high80']:,.0f}",
                              '同目标价修订':f"{r['change']:+.2f}" if r['same_target'] else '滚动窗口，目标已变'})
            st.dataframe(pd.DataFrame(table).style.format({'上次中心价':'{:,.2f}','本次中心价':'{:,.2f}'}),hide_index=True,width='stretch')
        st.caption(diff['message']+' 两次目标日期不同时，不把中心价差当作同一预测的修订。')
        if diff['new'] or diff['revised']:
            with st.expander('本轮新收录与修订的消息'):
                for item in (diff['new']+diff['revised'])[:12]:
                    st.markdown(f"- {item['source']} · {message_time(item)} · [{item['title']}]({item['url']})")
    journal=context.get('journal')
    if journal:
        with st.expander('回看之前保存的预测与消息'):
            history=journal.history(12)
            chosen=st.selectbox('历史快照',history,format_func=lambda r:f"#{r['id']} · {local_stamp(r['captured_at'])} 北京时间",key='analysis_history')
            if chosen:
                payload=chosen['payload']
                st.caption(f"当时价格基准：{payload.get('reference_date')}；模型生成：{local_stamp(payload.get('model_generated_at'))} 北京时间。")
                if payload.get('forecast_rows'):
                    frame=pd.DataFrame(payload['forecast_rows'])[['h','date','center','low80','high80']]
                    frame.columns=['交易日周期','当时目标日','中心情景价','理论80%下沿','理论80%上沿']
                    st.dataframe(frame.style.format({'中心情景价':'{:,.2f}','理论80%下沿':'{:,.2f}','理论80%上沿':'{:,.2f}'}),hide_index=True,width='stretch')
                for item in payload.get('messages',[])[:8]:st.markdown(f"- {item.get('source','')} · [{item.get('title','')}]({item.get('url','')})")
            st.caption('保存最近500个有效快照，数据相同时不重复写入。Streamlit云端实例重建后本地历史可能丢失；不是完整的长期回测数据库。')


def render_news_stress(context):
    st.markdown('### 消息面与风险情景')
    messages=context.get('messages',[])
    groups={}
    for item in messages:
        category=item.get('analysis',{}).get('category','未分类');groups[category]=groups.get(category,0)+1
    if groups:st.caption('最近7天已收录：'+' · '.join(f'{k} {v}条' for k,v in groups.items())+'。条数不代表影响权重，也不是概率。')
    forecast=context.get('forecast')
    if not forecast:
        st.info('当前没有有效统计预测，暂不能生成数值压力边界。')
        return
    st.caption('新闻先更新事实与传导假设；统计区间依据有效市场数据重新计算。尚无校准后的新闻影响幅度模型，不按“鹰派/战争”标题自动加减金价。')
    with st.expander('选择假设，查看额外风险压力边界'):
        scenarios={'baseline':'不额外加入消息冲击','pressure':'假设利率/美元上行形成额外压力','support':'假设利率/美元下行形成额外支持','geopolitics':'假设地缘风险带来双向波动','energy':'假设能源供给冲击带来双向波动'}
        scenario=st.selectbox('消息传导假设',list(scenarios),format_func=scenarios.get,key='news_stress_scenario')
        multiple=st.slider('额外冲击强度：该周期历史波动的倍数',0.0,2.0,0.0,.25,key='news_stress_multiple')
        h=st.session_state.get('forecast_horizon',7)
        result=stress_range(forecast,h,scenario,multiple)
        a,b=st.columns(2)
        a.metric('统计模型理论80%区间',f"{result['baseline_low']:,.0f}–{result['baseline_high']:,.0f}")
        b.metric('用户假设的压力边界',f"{result['low']:,.0f}–{result['high']:,.0f}")
        st.warning('右侧没有80%或95%的覆盖率含义，不是新闻自动预测或已验证胜率。强度由你选择，不是系统从新闻估出的价格冲击。')
        st.caption(f"周期{h}个交易日；额外对数冲击 = 日波动率 × √周期 × 所选倍数。压力情景只向下扩展，支持情景只向上扩展，双向情景扩展两侧；不改动统计模型的中心价和概率。")


def render_message_center(context):
    st.markdown('### 美联储讲话、能源与地缘消息')
    render_activity(context)
    render_policy_energy(context)
    speeches=context.get('speeches',[])
    st.markdown('### 按官员查看已取得的讲话')
    st.caption('官方理事会讲话/证词与12家地区联储索引独立检查。成功取得的条目才进入列表；不代表覆盖全部官员采访、即席发言或未公布文本。')
    if speeches:
        people=['全部']+sorted({i.get('speaker_zh') or i.get('speaker','待识别') for i in speeches})
        person=st.selectbox('官员',people,key='speech_person')
        selected=[i for i in speeches if person=='全部' or (i.get('speaker_zh') or i.get('speaker','待识别'))==person]
        for item in selected[:12]:
            with st.container(border=True):
                st.markdown(f"**{item.get('speaker_zh') or item.get('speaker','待识别')} · {item['title']}**")
                st.caption(item['source']+' · '+message_time(item))
                st.write(item.get('summary','暂未取得摘要'))
                st.markdown('**政策措辞识别：'+item.get('stance','待判断')+'**')
                if item.get('topics'):st.caption('正文议题：'+'、'.join(item['topics']))
                for evidence in item.get('evidence',[]):st.caption('原文短摘句（截断）：'+evidence)
                st.caption(item.get('method','标题记录')+'。个人发言不是FOMC集体决定，不按鹰鸽条数推算加息概率。')
                if item.get('body_error'):st.caption('本轮正文读取：'+item['body_error'])
                st.markdown(f"[官方原文 ↗]({item['url']})")
    else:st.info('讲话索引仍在后台采集或来源不可用，不用旧新闻冒充本轮新讲话。')
    with st.expander('官方讲话来源覆盖与失败原因'):
        coverage=[]
        for key,(name,url,mode) in SOURCES.items():
            entry=context['feeds'].get('speeches:'+key,{})
            items=(entry.get('data') or {}).get('items',[])
            coverage.append({'来源':name,'已取得条目':len(items),'取得正文':sum(bool(i.get('full_text_obtained')) for i in items),
                             '状态':entry.get('status','尚未检查'),'最近检查':local_stamp(entry.get('checked_at') or entry.get('fetched_at')),
                             '错误':entry.get('error',''),'官方入口':url})
        st.dataframe(pd.DataFrame(coverage),hide_index=True,width='stretch',column_config={'官方入口':st.column_config.LinkColumn('官方入口')})
    st.markdown('### 最近7天消息与验证条件')
    st.caption('新闻按黄金、宏观、政策、能源及地缘关键词筛选；官方讲话另行保留。规则可能漏掉间接相关事件，不代表全部新闻。')
    messages=context.get('messages',[])
    categories=['全部']+sorted({i['analysis']['category'] for i in messages})
    category=st.selectbox('消息类别',categories,key='message_category')
    selected=[i for i in messages if category=='全部' or i['analysis']['category']==category]
    for item in selected[:16]:
        a=item['analysis']
        with st.container(border=True):
            st.markdown(f"**{item['title']}**")
            st.caption(f"{item['source']} · {message_time(item)} · {item.get('time_kind','来源时间')}")
            st.write(f"{a['category']} · {a['direction']}")
            st.write('传导假设：'+a['path'])
            st.write('相反力量：'+a['counter'])
            st.caption('验证：'+a['validation']+' · '+a['basis'])
            st.markdown(f"[来源原文 ↗]({item['url']})")
    if not selected:st.info('当前筛选没有已取得的近期消息，不等于没有事件。')
