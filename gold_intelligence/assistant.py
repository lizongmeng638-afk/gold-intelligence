"""Free deterministic Q&A over current site data; no external LLM or hidden API."""
import re

from .domestic import comparable
from .feeds import safe_url
from .gold_logic import DRIVERS, EVENTS
from .history import choose_history, fibonacci
from .intelligence import factor_conclusion, local_stamp, model_groups
from .models import classify_news
from .rate_freshness import rate_freshness
from .yields import resolve_rates, rate_summary


def horizon_from_text(question):
    question=question.lower()
    numeric=re.search(r'(\d+)\s*(个交易日|交易日|天|日|小时|个月|月|周)',question)
    if numeric:
        count,unit=int(numeric[1]),numeric[2]
        h=count*30 if unit in ('个月','月') else count*7 if unit=='周' else (1 if count==24 else -1) if unit=='小时' else count
        return h if h in (1,3,7,30,90) else None
    if any(k in question for k in ['后天','两天','两个月','两周','明年','后年','年底']) or re.search(r'20\d{2}年',question):return None
    if any(k in question for k in ['明天','24小时','24h','一天','1天']):return 1
    for h,words in [(90,['90','九十','三个月']),(30,['30','三十','一个月']),(7,['7','七天','一周']),(3,['3','三天'])]:
        if any(w in question for w in words):return h
    return 7


def forecast_answer(context,question):
    ready,forecast=context['readiness'],context.get('forecast')
    if not ready['ready']:
        return f"**暂未生成预测。** {ready['message']}\n\n{ready['schedule']}。数据就绪后自动尝试，不保证免费来源返回新数据的具体时间。"
    if not forecast:
        return '期货价格已取得，但有效训练样本或近期因子不足，目前没有可用预测。请查看首页的数据状态；不会把旧示例当作最新结果。'
    horizon=horizon_from_text(question)
    if horizon is None:return '当前只提供约24小时（1个交易日）、3、7、30、90个交易日的情景估计，不提供该指定日期或周期。可以改问“未来7个交易日区间”。'
    row=next(r for r in forecast['rows'] if r['h']==horizon)
    lead='无法确定具体哪天必涨或必跌，也不能据此确定买入时机。以下是当前模型情景。\n\n' if re.search(r'(什么时候|何时).*(涨|跌|买)',question) or '买入时机' in question else ''
    if '24小时' in question:lead+='系统暂不提供严格自然24小时预测；下面展示1个交易日的日线情景，两者可能跨不同的自然时间。\n\n'
    return (lead+f"**未来{horizon}个交易日的统计情景**（目标日期参考 {row['date'].date()}）：\n\n"
            f"- 中心情景价：**${row['center']:,.2f}/金衡盎司**。\n"
            f"- 理论80%区间：${row['low80']:,.2f}—${row['high80']:,.2f}；理论95%区间：${row['low95']:,.2f}—${row['high95']:,.2f}。\n"
            f"- 上涨/震荡/下跌情景概率：{row['up']:.1%} / {row['flat']:.1%} / {row['down']:.1%}。\n\n"
            f"基准为 GC=F 黄金期货日线 **${ready['reference']:,.2f}，{ready['reference_date']}**；因子日期 {forecast['feature_date']}，生成于 {local_stamp(forecast.get('generated_at'))} 北京时间。\n\n"
            '情景概率来自分布假设，区间覆盖率尚未校准；不是现货、人民币报价或已验证胜率。上涨/下跌以终点收益超出±0.35倍该周期估计波动为界。日期只排除周末，未计交易所假日。')


def update_answer(context):
    ready,forecast=context['readiness'],context.get('forecast')
    if not ready['ready'] or not forecast:return forecast_answer(context,'预测什么时候出')
    return (f"**现在已经可以查看预测。** 本次生成于 **{local_stamp(forecast.get('generated_at'))} 北京时间**。\n\n"
            f"价格基准日 {ready['reference_date']}，因子日 {forecast['feature_date']}。{ready['schedule']}。\n\n"
            '行情通常每小时检查、关键收益率每15分钟检查。收到新的有效日线或因子后重新计算；每小时检查不代表来源每小时都有新观测。休市、限流或超时会延后，页面会保留时间标记。')


def factor_answer(context,question):
    factors=context['factors']
    conclusion=factor_conclusion(factors)
    filtered=factors
    if any(k in question for k in ['美元','dxy']):filtered=[f for f in factors if f['id']=='DXY']
    elif any(k in question for k in ['实际利率','实际收益率','tips']):filtered=[f for f in factors if f['id']=='DFII10']
    lines=[f"**{conclusion['label']}**：{conclusion['text']}",
           '阅读时优先核对实际收益率和美元。这是观察顺序，影响强弱随时期变化，不能据此给出固定百分比权重。']
    for factor in filtered:
        lines.append(f"**{factor['name']}**：{factor['value']}；{factor['change']}；观测日 {factor['date']}。黄金影响：{factor['effect']}。{factor['explanation']} 核验状态：{factor.get('verification','尚待核验')}。[{factor['name']}来源]({factor['url']})")
    return '\n\n'.join(lines)


def quality_answer(context):
    forecast=context.get('forecast')
    if not forecast:return forecast_answer(context,'预测')
    acc,baseline=forecast.get('acc'),forecast.get('baseline_acc')
    if acc is None:return '当前使用历史统计基线，尚没有可报告的有效留出集准确率，也没有各周期的已验证胜率。'
    comparison=f"同一留出集的简单基准为 {baseline:.1%}。" if baseline is not None else ''
    return (f"当前日线模型留出集方向准确率为 **{acc:.1%}**（{forecast.get('validation_count','未提供')}条）。{comparison}\n\n"
            '这不是未来7天或30天的预测胜率；理论80%/95%区间没有完成分周期覆盖率校准。单次时间顺序留出检验不足以证明持续预测能力。\n\n'
            f"实际使用因子：{'、'.join(model_groups(forecast)) or '历史价格统计'}。监测卡片里的因子不一定进入模型，历史不足时会被排除。")


def domestic_answer(context):
    feed=context['feeds'].get('cn:history',{})
    history=feed.get('data') or {}
    rows=history.get('rows',[])
    lines=[]
    if rows:
        lines.append(f"上海黄金交易所 Au99.99 最新已取得的日收盘参考是 **{rows[-1]['value']:,.2f} 元/克**，观测日 **{rows[-1]['date']}**。[上金所原始行情]({history.get('url','https://www.sge.com.cn/sjzx/quotation_daily_new')})。这不是银行积存金成交价。")
    quotes=((context['feeds'].get('cn:retail',{}) or {}).get('data') or {}).get('quotes',[])
    eligible=[r for r in quotes if r['category']=='品牌金饰' and r['purity']=='999足金' and r['side']=='买入']
    if eligible:
        date=max(r['date'] for r in eligible)
        group=comparable(eligible,'品牌金饰','999足金',date,side='买入')
        if len(group)>=2:
            low=[r['channel'] for r in group if r['price']==group[0]['price']]
            high=[r['channel'] for r in group if r['price']==group[-1]['price']]
            lines.append(f"同日同类999足金挂牌（{date}）中，最低 **{group[0]['price']:,.2f} 元/克**（{'、'.join(sorted(set(low)))}），最高 **{group[-1]['price']:,.2f} 元/克**（{'、'.join(sorted(set(high)))}）。这里只比较已接入的 SMM 公开挂牌，通常还需另核工费和门店优惠。")
    return '\n\n'.join(lines) if lines else '当前国内报价尚未取得。请查看“国内比价”及“数据诊断”；缺失数据不会当作0元或最低价。'


def fib_answer(context):
    daily=((context['feeds'].get('market:GC=F',{}) or {}).get('data') or {}).get('rows',[])
    rows=daily[-250:] if len(daily)>=2 else choose_history(context['feeds'].get('history:gold',{}))['rows'][-60:]
    basis='默认近250个观测日 GC=F 期货日线' if len(daily)>=2 else '最近60个月黄金月均价'
    try:info=fibonacci(rows)
    except (ValueError,KeyError):return '当前有效价格不足或波段价格相同，暂不能计算斐波那契。'
    lines=[f"按 **{basis}，自动高低点** 计算：{info['direction']}，A {info['a']['date']}（${info['a']['value']:,.2f}）→ B {info['b']['date']}（${info['b']['value']:,.2f}）。"]
    for level in info['levels']:
        if level['ratio'] in (.382,.5,.618,1.272,1.618) and level['value']>0:
            lines.append(f"- {level['kind']} {level['ratio']:.1%}：${level['value']:,.2f}。")
    lines.append('这是默认参数的独立回答，不同步手动选点。完整图和手动取点在“逻辑与历史”。这些是技术观察位，不是内在价值、必达目标或买入信号。')
    return '\n\n'.join(lines)


def price_answer(context):
    entry=context['feeds'].get('quote',{}) or {}
    quote=entry.get('data') or {}
    if quote:
        return f"当前站内现货参考 **${quote['price']:,.2f}/金衡盎司**；来源标注时间 **{local_stamp(quote['observed_at'])} 北京时间**，来源 {quote['source']}，连接状态：{entry.get('status','待核验')}。免费报价可能延迟；预测采用另外的 GC=F 期货日线，两者不混用。"
    ready=context['readiness']
    if ready.get('reference'):
        return f"现货暂不可用。已取得的 GC=F 期货日线参考为 **${ready['reference']:,.2f}**（{ready['reference_date']}）；不是现货报价。"
    return '现货与期货有效报价暂未取得，请查看数据诊断。'


def rate_answer(context,question):
    sid='DGS2' if any(k in question for k in ['2年','两年']) else 'DFII10' if '实际' in question else 'DGS10'
    label={'DGS2':'2年期名义收益率','DFII10':'10年期实际收益率','DGS10':'10年期名义收益率'}[sid]
    rows=resolve_rates(context['feeds']).get(sid,[])
    info=rate_summary(rows)
    if not info:return f'{label}当前没有有效观测值，请查看宏观指标及数据诊断。'
    freshness=rate_freshness(rows,context['feeds'],sid)
    delta=info.get('change_bp')
    change=f"较 {info['previous_date']} 变化 {delta:+.1f} 基点" if delta is not None else '不足两个有效观测值，暂无涨跌变化'
    return f"**{label}：{info['value']:.2f}%**，观测日 {info['date']}；{change}。\n\n{freshness['label']}。名义与实际收益率是不同指标；这是官方日度观测，不是盘中逐笔报价。[数据定义](https://fred.stlouisfed.org/series/{sid})"


def news_answer(context):
    items=context.get('news') or []
    if not items:return '当前没有取得可展示的新闻。历史事件仍可在“逻辑与历史”查看，不会用历史事件冒充今天新闻。'
    lines=['以下是站内已经取得的新闻标题记录，时间可能延迟；只做标题规则分类，未核验全文，不能直接换算成涨跌幅。']
    used=set()
    for item in items:
        source=item.get('source','来源未提供')
        if source in used:continue
        url=safe_url(item.get('url'))
        if not url:continue
        used.add(source)
        category,direction,chain,verification=classify_news(item)
        lines.append(f"**{source}** · {local_stamp(item.get('date'))} 北京时间\n\n标题规则分类：{category}；方向假设：{direction}。验证：{verification} [查看原始记录]({url})")
        if len(used)>=3:break
    return '\n\n'.join(lines)


def answer_question(question,context,previous_question=''):
    q=question.strip().lower()
    if not q:return '可以问我当前站内价格、未来区间、重要因子、预测更新时间、国内比价或斐波那契。'
    if len(q)>800:return '问题请控制在800字以内，可以拆成几个站内数据问题。'
    if '预测' in q and any(k in q for k in ['没有','不能','不出','暂时']):return forecast_answer(context,q)
    if any(k in q for k in ['准确','靠谱','胜率','准不准','回测','可靠吗','可靠性','confidence']):return quality_answer(context)
    if any(k in q for k in ['更新','什么时候出','何时出','多久出','刷新','何时生成','什么时候生成']):return update_answer(context)
    if any(k in q for k in ['新闻','最新事件','最近事件','今天的事件','国际事件']):return news_answer(context)
    if '收益率' in q and any(k in q for k in ['2年','两年','名义','10年']):return rate_answer(context,q)
    if any(k in q for k in ['国内','渠道','人民币','元/克','最低价','最高价','金店','便宜']):return domestic_answer(context)
    if any(k in q for k in ['斐波','fibonacci','61.8','38.2','支撑','阻力','回撤位']):return fib_answer(context)
    if any(k in q for k in ['因子','影响','原因','为什么','看涨','看跌','利多','利空','美元','dxy','收益率','实际利率','vix','原油']):return factor_answer(context,q)
    if any(k in q for k in ['预测','未来','明天','后天','走势','明年','年底','何时上涨','何时下跌','买入时机']) or re.search(r'(什么时候|何时).*(涨|跌|买)|\d+\s*(天|日|小时|周|个月)',q):
        return forecast_answer(context,q)
    if any(k in q for k in ['历史','1971','事件','黄金的价值']):
        return ('黄金的货币地位、实际利率、货币信心与需求共同影响定价。“逻辑与历史”整理了1971年以来月均价和12个关键事件；每条都分开列出事实、传导假设、相反力量和来源。\n\n'
                f"例如：{EVENTS[0]['date']} {EVENTS[0]['title']}。[美联储历史资料]({EVENTS[0]['url']})。这不代表所有节点都能解释为某个单一事件造成。")
    if any(k in q for k in ['价格','金价','多少钱','报价','行情']):return price_answer(context)
    if previous_question and any(k in q for k in ['再说','继续','具体点','详细点','那呢','为什么呢']):
        return answer_question(previous_question,context)
    return ('我是免费的站内数据助手，按当前页面数据和规则回答，还不是能自由推理的大模型。\n\n可以问：**未来7天区间？最重要的因子？预测什么时候更新？准确率怎样？国内哪里便宜？斐波那契价位？**')
