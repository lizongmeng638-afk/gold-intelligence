"""Bounded official speech collection. Coverage and title-only gaps stay visible."""
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from html import unescape
from html.parser import HTMLParser
import re
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree as ET

from .activity import text_only
from .feeds import FeedError, get_bytes, normalize_news, parse_time, iso_now, valid_time

SOURCES={
 'board':('美联储理事会','https://www.federalreserve.gov/feeds/speeches_and_testimony.xml','rss'),
 'boston':('波士顿联储','https://www.bostonfed.org/news-and-events/speeches.aspx','index'),
 'newyork':('纽约联储','https://www.newyorkfed.org/newsevents/speeches','index'),
 'philadelphia':('费城联储','https://www.philadelphiafed.org/the-economy/speeches-anna-paulson','index'),
 'cleveland':('克利夫兰联储','https://www.clevelandfed.org/collections/speeches','index'),
 'richmond':('里士满联储','https://www.richmondfed.org/press_room/speeches','index'),
 'atlanta':('亚特兰大联储','https://www.atlantafed.org/news/speeches','index'),
 'chicago':('芝加哥联储','https://www.chicagofed.org/utilities/about-us/office-of-the-president/office-of-the-president-speaking','index'),
 'stlouis':('圣路易斯联储','https://www.stlouisfed.org/from-the-president/speeches-and-presentations','index'),
 'minneapolis':('明尼阿波利斯联储','https://www.minneapolisfed.org/news-and-events','index'),
 'kansascity':('堪萨斯城联储','https://www.kansascityfed.org/speeches','index'),
 'dallas':('达拉斯联储','https://www.dallasfed.org/news/speeches/logan','index'),
 'sanfrancisco':('旧金山联储','https://www.frbsf.org/news-and-media/speeches/mary-c-daly','index'),
}
NAMES={'Jefferson':'杰斐逊','Warsh':'沃什','Waller':'沃勒','Bowman':'鲍曼','Cook':'库克','Barr':'巴尔','Powell':'鲍威尔','Williams':'威廉姆斯','Collins':'柯林斯','Paulson':'保尔森','Hammack':'哈马克','Barkin':'巴尔金','Goolsbee':'古尔斯比','Musalem':'穆萨莱姆','Kashkari':'卡什卡利','Schmid':'施密德','Logan':'洛根','Daly':'戴利'}
VOID={'br','img','input','meta','link','hr','source','wbr','area','base','embed','param','track'}


class OfficialHTML(HTMLParser):
    def __init__(self):
        super().__init__();self.stack=[];self.parts=[];self.main=[];self.speaker=[];self.links=[];self.anchor=None;self.published=None
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='meta' and (a.get('property') in ('article:published_time','og:published_time') or a.get('name') in ('date','pubdate','DC.date.issued')):
            self.published=a.get('content')
        if tag=='time' and a.get('datetime'):self.published=self.published or a['datetime']
        if tag=='a':self.anchor={'url':a.get('href',''),'text':[],'offset':len(self.parts)}
        if tag not in VOID:self.stack.append((tag,a))
    def handle_endtag(self,tag):
        if tag=='a' and self.anchor:
            self.links.append({'url':self.anchor['url'],'title':' '.join(self.anchor['text']).strip(),'offset':self.anchor['offset']});self.anchor=None
        for i in range(len(self.stack)-1,-1,-1):
            if self.stack[i][0]==tag:self.stack=self.stack[:i];break
    def handle_data(self,data):
        if any(t in ('script','style','nav','footer','header') for t,_ in self.stack):return
        value=re.sub(r'\s+',' ',unescape(data)).strip()
        if not value:return
        self.parts.append(value)
        if any(t=='main' or a.get('id')=='article' or any(k in a.get('class','') for k in ('article__content','field--name-body','article-body','body-content')) for t,a in self.stack):self.main.append(value)
        if any('speaker' in a.get('class','').split() for _,a in self.stack):self.speaker.append(value)
        if self.anchor:self.anchor['text'].append(value)


def source_url(url,source_url):
    u=urlparse(url);s=urlparse(source_url)
    return u.scheme=='https' and u.hostname and u.hostname.removeprefix('www.')==s.hostname.removeprefix('www.') and not u.username and not u.password


def guessed_date(url):
    for pattern in (r'(20\d{2})/?(0[1-9]|1[0-2])/?([0-2]\d|3[01])',r'/(20\d{2})/(\d{1,2})/(\d{1,2})/'):
        found=re.search(pattern,url)
        if found:
            try:return valid_time(f'{int(found[1]):04d}-{int(found[2]):02d}-{int(found[3]):02d}')
            except (ValueError,FeedError):pass
    short=re.search(r'/(?:20(\d{2})/)?[a-z_-]*(\d{2})(0[1-9]|1[0-2])([0-2]\d|3[01])(?:[-/.]|$)',url,re.I)
    if short and (not short[1] or short[1]==short[2]):
        try:return valid_time(f'20{short[2]}-{short[3]}-{short[4]}')
        except (ValueError,FeedError):pass
    return None


def prose_date(text):
    match=re.search(r'\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),\s+(20\d{2})\b',text)
    if not match:return None
    return datetime.strptime(match[0],'%B %d, %Y').date().isoformat()


FULL_NAMES=('Philip N. Jefferson','Kevin Warsh','Christopher J. Waller','Michelle W. Bowman','Lisa D. Cook','Michael S. Barr','Jerome H. Powell','John C. Williams','Susan M. Collins','Anna Paulson','Beth M. Hammack','Thomas I. Barkin','Austan D. Goolsbee','Austan Goolsbee','Alberto G. Musalem','Alberto Musalem','Neel Kashkari','Jeffrey R. Schmid','Lorie K. Logan','Mary C. Daly')


def named_speaker(text):
    for name in FULL_NAMES:
        if name.lower() in text.lower():return name
    return ''


def speech_summary(body,title):
    lower=body.lower()
    topics=[]
    for label,terms in [('通胀与物价',('inflation','price stability')),('利率与政策',('monetary policy','policy rate','interest rate')),('就业与增长',('employment','economic growth','labor market')),('能源与地缘冲击',('oil','energy prices','geopolitical','supply shock')),('金融稳定',('financial stability','capital buffer')),('支付与技术',('payments','tokeniz','artificial intelligence','productivity'))]:
        if any(re.search(r'\b'+re.escape(t),lower) for t in terms):topics.append(label)
    hawk=('further tightening','additional rate increases','higher for longer','raise interest rates','raise the target range','inflation remains too high','not yet sufficiently restrictive')
    dove=('lower the target range','cut interest rates','reduce interest rates','rate cuts are appropriate','begin reducing rates','ease monetary policy')
    def present(phrase):
        for match in re.finditer(re.escape(phrase),lower):
            before=lower[max(0,match.start()-55):match.start()]
            sentence_start=max(lower.rfind('.',0,match.start()),lower.rfind('!',0,match.start()),lower.rfind('?',0,match.start()))+1
            sentence=lower[sentence_start:match.start()]
            if re.search(r'\b(?:markets?|investors?|analysts?)\s+(?:had\s+)?(?:expected|anticipated|priced|forecast)',sentence):continue
            if not re.search(r'\b(?:not|no|never|unlikely)\b[^.!?]{0,45}$',before):return True
        return False
    h=[p for p in hawk if present(p)];d=[p for p in dove if present(p)]
    stance='鹰鸽线索并存' if h and d else '偏鹰线索' if h else '偏鸽线索' if d else '未识别明确利率方向'
    if 'supply shock' in lower and 'demand shock' in lower:
        summary='正文区分供给冲击与需求冲击；两类冲击对增长、物价和政策的作用可能不同，不能仅凭能源或通胀上升直接推断加息。'
    elif h or d:
        summary='正文出现'+('偏鹰与偏鸽' if h and d else '偏鹰' if h else '偏鸽')+'政策措辞线索；需要区分历史投票、个人偏好、条件假设与未来承诺，不能直接推断下一次会议行动。'
    elif 'financial stability' in lower and len(topics)<=2:
        summary='正文讨论金融稳定风险；金融稳定讲话不自动等于下一次利率决定。'
    elif topics:
        summary='正文涉及'+'、'.join(topics[:3])+'；以下为规则识别的议题和措辞，需要结合完整语境核对。'
    else:summary='已取得正文，但规则未能形成可靠的政策摘要，请阅读原文。'
    evidence=[]
    sentences=re.split(r'(?<=[.!?])\s+',body)
    for sentence in sentences:
        if any(p in sentence.lower() for p in h+d) or ('supply shock' in sentence.lower() and not h and not d):
            evidence=[' '.join(sentence.split()[:20])+(' …' if len(sentence.split())>20 else '')];break
    return {'summary':summary,'topics':topics,'stance':stance,'hawkish_phrases':h,'dovish_phrases':d,'evidence':evidence,
            'method':'官方正文规则摘要，非AI深度解读','full_text_obtained':True}


def message_time(item):
    """Preserve a date-only source without inventing a UTC or Beijing time."""
    if not item.get('date'):return '发布时间未核验'
    if '精确时刻待核验' in item.get('time_kind',''):
        return str(item['date'])[:10]+'（官方网页日期；具体时刻未提供）'
    from .intelligence import local_stamp
    return local_stamp(item['date'])+' 北京时间'


@lru_cache(maxsize=180)
def article_details(url,host_url,quarter_hour):
    if not source_url(url,host_url):raise FeedError('讲话链接不属于该官方来源，未读取')
    raw=get_bytes(url,timeout=(4,7),deadline_seconds=12,max_bytes=1_500_000).decode('utf-8-sig')
    if re.search(r'captcha|verify you are human|access denied',raw,re.I):raise FeedError('正文访问受限，未绕过验证')
    parser=OfficialHTML();parser.feed(raw)
    body=' '.join(parser.main or parser.parts)
    if len(body.split())<180:raise FeedError('未取得足够的讲话正文，可能只有视频或索引；未作全文摘要')
    date=prose_date(body[:1800]) or parser.published
    speaker=named_speaker(' '.join(parser.speaker)) or named_speaker(body[:2400])
    return {**speech_summary(body[:50000],''),'speaker':speaker,'article_date':date,'body_checked_at':iso_now()}


def rss_speeches(content,source):
    try:root=ET.fromstring(content)
    except ET.ParseError as exc:raise FeedError('讲话源不是有效RSS/XML') from exc
    items=[]
    for node in root.findall('.//item'):
        title=node.findtext('title','').strip();url=node.findtext('link','').strip()
        if not source_url(url,source):continue
        stamp=node.findtext('pubDate') or node.findtext('{http://purl.org/dc/elements/1.1/}date')
        try:date=valid_time(stamp)
        except (ValueError,TypeError,FeedError):continue
        items.append({'title':title,'url':url,'date':date,'description':text_only(node.findtext('description',''))[:600],
                      'speaker':title.split(',',1)[0] if ',' in title else '未识别','time_kind':'官方发布时间'})
    return sorted(items,key=lambda a:a['date'],reverse=True)


def fetch_speeches(key):
    name,url,mode=SOURCES[key];content=get_bytes(url,timeout=(4,7),deadline_seconds=12,max_bytes=1_500_000)
    if mode=='rss':items=rss_speeches(content,url)[:24]
    else:
        raw=content.decode('utf-8-sig')
        if re.search(r'captcha|verify you are human|access denied',raw,re.I):raise FeedError(name+'索引访问受限，未绕过验证')
        parser=OfficialHTML();parser.feed(raw);candidates={}
        for link in parser.links:
            target=urljoin(url,link['url']).split('#')[0]
            speech_path=re.search(r'speech|remarks|testimony',target,re.I) or (key=='philadelphia' and '/monetary-policy/' in target)
            if not source_url(target,url) or not speech_path or target.rstrip('/')==url.rstrip('/'):continue
            if 'system-speeches' in target or target.lower().endswith('.pdf'):continue
            if len(link['title'])<12:continue
            near=' '.join(parser.parts[link['offset']:link['offset']+6])
            date=guessed_date(target)
            if not date:
                try:date=valid_time(prose_date(near)) if prose_date(near) else None
                except (ValueError,FeedError):continue
            if not date and not re.search(r'20\d{2}',target):continue
            if date and not 0<=(datetime.now(timezone.utc)-parse_time(date)).total_seconds()<=90*86400:continue
            # Preserve the official index ordering for undated slugs; lexical
            # ordering previously elevated 2005 archive articles above 2026.
            years=[int(v) for v in re.findall(r'(?<!\d)(20\d{2})(?!\d)',target)]
            if years and max(years)<datetime.now(timezone.utc).year-1:continue
            speaker=named_speaker(near) or (link['title'].split(':',1)[0] if ':' in link['title'] else '待识别')
            candidates[target]={'url':target,'title':link['title'],'date':date,'speaker':speaker,'time_kind':'官方网页日期，精确时刻待核验'}
        items=list(candidates.values())[:8]
    if not items:raise FeedError(name+'未取得可解析的讲话条目；不等于没有讲话')
    now=datetime.now(timezone.utc)
    selected=[];people=set()
    for i,item in enumerate(items):
        person=item.get('speaker','').lower()
        if mode=='rss' and person not in people and len(selected)<7:
            people.add(person);selected.append(i)
        elif mode!='rss' and i<2:selected.append(i)
    details={}
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures={i:pool.submit(article_details,items[i]['url'],url,int(now.timestamp()//900)) for i in selected}
        for i,future in futures.items():
            try:details[i]=future.result()
            except Exception as exc:details[i]={'body_error':str(exc)[:180]}
    for index,item in enumerate(items):
        item.update(source=name,source_key=key,summary='仅取得标题/索引，本轮未取得正文，不据此判断鹰鸽。',
                    stance='尚未核验正文',topics=[],evidence=[],full_text_obtained=False,method='标题或索引记录')
        if index in details:
            detail=dict(details[index]);speaker=detail.pop('speaker',None)
            item.update(detail)
            if speaker:item['speaker']=speaker
            if not item.get('date') and detail.get('article_date'):
                try:item['date']=valid_time(detail['article_date'])
                except (ValueError,FeedError):pass
        for token,chinese in NAMES.items():
            if token.lower() in item['speaker'].lower():item['speaker_zh']=chinese;break
    items=[i for i in items if not i.get('date') or 0<=(now-parse_time(i['date'])).total_seconds()<=90*86400]
    if not items:raise FeedError(name+'未取得90天内有效条目；不等于没有讲话')
    items.sort(key=lambda i:i.get('date') or '',reverse=True)
    observed=max((item['date'] for item in items if item.get('date')),default=None)
    return {'items':items,'source':name+'官方讲话','url':url,'observed_at':observed,
            'coverage_note':'覆盖成功取得的官方条目，不代表全部采访或未公布发言。理事会尝试按每位官员最新一篇读取正文（最多7位），地区分行尝试最新两篇；正文缓存15分钟。'}


def collected_speeches(feeds):
    items={}
    for key,feed in feeds.items():
        if not key.startswith('speeches:'):continue
        for item in (feed.get('data') or {}).get('items',[]):
            if item.get('date'):
                try:
                    if not 0<=(datetime.now(timezone.utc)-parse_time(item['date'])).total_seconds()<=90*86400:continue
                except (ValueError,TypeError):continue
            old=items.get(item['url'])
            if old is None or (item.get('full_text_obtained') and not old.get('full_text_obtained')):items[item['url']]={**item,'feed_key':key,'feed_error':feed.get('error','')}
    return sorted(items.values(),key=lambda a:a.get('date') or '',reverse=True)
