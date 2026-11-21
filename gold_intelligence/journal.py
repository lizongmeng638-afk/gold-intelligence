"""A small persistent public-data journal for meaningful refresh comparisons."""
from datetime import datetime,timezone
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import threading

from .event_analysis import message_key


def snapshot_payload(context):
    forecast=context.get('forecast')
    rows=[]
    for r in (forecast or {}).get('rows',[]):
        rows.append({k:(str(v.date()) if k=='date' and hasattr(v,'date') else v) for k,v in r.items()})
    messages=[]
    for item in context.get('messages',[]):
        messages.append({k:item.get(k) for k in ('key','url','title','date','source','speaker','stance','full_text_obtained','summary','analysis') if item.get(k) is not None})
    return {'reference_date':context['readiness'].get('reference_date'),'reference':context['readiness'].get('reference'),
            'forecast_rows':rows,'model_version':(forecast or {}).get('model_version'),'model_generated_at':(forecast or {}).get('generated_at'),
            'feature_date':(forecast or {}).get('feature_date'),'messages':messages,
            'activity':{k:{field:v.get(field) for field in ('period','value','previous','mom','yoy','previous_mom','snapshot')} for k,v in context.get('activity',{}).items()}}


def fingerprint(payload):
    content={k:v for k,v in payload.items() if k!='model_generated_at'}
    content['messages']=sorted(content.get('messages',[]),key=lambda i:i['key'])
    return hashlib.sha256(json.dumps(content,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()


def snapshot_diff(current,previous):
    if not previous:return {'first':True,'new':[],'revised':[],'range_changes':[],'message':'首次建立对照；已有消息不等于刚刚发生。'}
    old={i['key']:i for i in previous.get('messages',[])}
    new=[i for i in current.get('messages',[]) if i['key'] not in old]
    revised=[i for i in current.get('messages',[]) if i['key'] in old and i!=old[i['key']]]
    before={r['h']:r for r in previous.get('forecast_rows',[])}
    changes=[]
    for row in current.get('forecast_rows',[]):
        earlier=before.get(row['h'])
        if earlier:
            same=earlier['date']==row['date']
            changes.append({'h':row['h'],'target':row['date'],'previous_target':earlier['date'],
                            'center':row['center'],'previous_center':earlier['center'],
                            'same_target':same,'change':row['center']-earlier['center'] if same else None,
                            'low80':row['low80'],'high80':row['high80'],'previous_low80':earlier['low80'],'previous_high80':earlier['high80']})
    return {'first':False,'new':new,'revised':revised,'range_changes':changes,
            'message':'新消息不自动变成价格修正；只有有效市场输入变化才重新计算统计预测。'}


class AnalysisJournal:
    def __init__(self,path,clock=None):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        self.clock=clock or (lambda:datetime.now(timezone.utc).timestamp());self.lock=threading.RLock()
        with self.connection() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE IF NOT EXISTS snapshots (id INTEGER PRIMARY KEY, fp TEXT, captured REAL, payload TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS messages (key TEXT PRIMARY KEY, first_seen REAL, last_seen REAL, payload TEXT)')
    @contextmanager
    def connection(self):
        db=sqlite3.connect(self.path,timeout=3)
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback();raise
        finally:db.close()
    def capture(self,payload,force=False,min_interval=30,allow_write=True):
        fp=fingerprint(payload);now=self.clock()
        encoded=json.dumps(payload,ensure_ascii=False,allow_nan=False)
        with self.lock,self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            last=db.execute('SELECT id,fp,captured,payload FROM snapshots ORDER BY id DESC LIMIT 1').fetchone()
            changed=last is None or last[1]!=fp
            wrote=bool(allow_write and changed and (last is None or force or now-last[2]>=min_interval))
            if wrote:
                db.execute('INSERT INTO snapshots(fp,captured,payload) VALUES(?,?,?)',(fp,now,encoded))
                for item in payload.get('messages',[]):
                    db.execute('INSERT INTO messages(key,first_seen,last_seen,payload) VALUES(?,?,?,?) ON CONFLICT(key) DO UPDATE SET last_seen=excluded.last_seen,payload=excluded.payload',
                               (item['key'],now,now,json.dumps(item,ensure_ascii=False)))
                db.execute('DELETE FROM snapshots WHERE id NOT IN (SELECT id FROM snapshots ORDER BY id DESC LIMIT 500)')
                db.execute('DELETE FROM messages WHERE key NOT IN (SELECT key FROM messages ORDER BY last_seen DESC LIMIT 2500)')
            records=db.execute('SELECT id,captured,payload FROM snapshots ORDER BY id DESC LIMIT 2').fetchall()
        current={'id':records[0][0],'captured_at':records[0][1],'payload':json.loads(records[0][2])} if records else None
        previous={'id':records[1][0],'captured_at':records[1][1],'payload':json.loads(records[1][2])} if len(records)>1 else None
        return {'current':current,'previous':previous,'wrote':wrote,'pending':changed and not wrote,
                'diff':snapshot_diff(current['payload'],previous['payload'] if previous else None) if current else None}
    def archived_messages(self,limit=100):
        with self.lock,self.connection() as db:
            rows=db.execute('SELECT first_seen,last_seen,payload FROM messages ORDER BY last_seen DESC LIMIT ?',(min(limit,250),)).fetchall()
        return [{**json.loads(p),'first_seen':first,'last_seen':last} for first,last,p in rows]
    def history(self,limit=12):
        with self.lock,self.connection() as db:
            rows=db.execute('SELECT id,captured,payload FROM snapshots ORDER BY id DESC LIMIT ?',(max(1,min(limit,30)),)).fetchall()
        return [{'id':i,'captured_at':t,'payload':json.loads(p)} for i,t,p in rows]
