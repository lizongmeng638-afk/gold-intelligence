from datetime import datetime, timezone
import streamlit as st

from .assistant import answer_question
from .intelligence import local_stamp


def render_assistant(context):
    st.markdown('### 黄金数据对话助手')
    st.caption('免费站内规则问答：读取已取得的行情、预测和来源，不调用付费AI，也不冒充通用大模型。输入内容不发送给外部AI；云端版由本网站服务器处理。')
    ready=context['readiness']
    st.caption(f"当前期货基准日：{ready.get('reference_date') or '尚未取得'}。历史回答保留当时的时间；重新提问会读取最新快照。")
    key='gold_qa_messages_v14'
    messages=st.session_state.setdefault(key,[])
    if st.button('清空当前对话',key='clear_gold_qa'):
        messages=[];st.session_state[key]=messages
    examples=['未来7天价格区间？','最重要的影响因子？','预测什么时候更新？','准确率靠谱吗？','国内哪里便宜？','斐波那契价位？']
    columns=st.columns(3)
    pending=None
    for i,question in enumerate(examples):
        if columns[i%3].button(question,key=f'gold_qa_example_{i}',width='stretch'):
            pending=question
    for message in messages:
        with st.chat_message(message['role']):
            st.markdown(message['content'])
            if message['role']=='assistant':st.caption('回答时间：'+message['at']+' 北京时间')
    typed=st.chat_input('例如：为什么偏弱？未来30天区间？',max_chars=800,key='gold_qa_input')
    question=typed or pending
    if question:
        previous=next((m['content'] for m in reversed(messages) if m['role']=='user'),'')
        now=local_stamp(datetime.now(timezone.utc).isoformat())
        response=answer_question(question,context,previous)
        for role,content in [('user',question),('assistant',response)]:
            with st.chat_message(role):
                st.markdown(content)
                if role=='assistant':st.caption('回答时间：'+now+' 北京时间')
            messages.append({'role':role,'content':content,'at':now})
        st.session_state[key]=messages[-24:]
