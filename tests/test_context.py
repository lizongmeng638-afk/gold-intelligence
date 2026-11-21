from copy import deepcopy
from datetime import datetime,timezone,timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from gold_intelligence.activity import bls_rows,ppi_measurement,parse_ism,activity_metrics,activity_assessment
from gold_intelligence.assistant import answer_question
from gold_intelligence.event_analysis import analyze_message,message_key,recent_messages,stress_range
from gold_intelligence.feeds import FeedError
from gold_intelligence.journal import AnalysisJournal,snapshot_diff,fingerprint,snapshot_payload
from gold_intelligence.models import classify_news
from gold_intelligence.speeches import guessed_date,prose_date,source_url,speech_summary,rss_speeches,fetch_speeches


class EconomicTests(unittest.TestCase):
    def test_ppi_uses_seasonal_monthly_and_nonseasonal_annual_changes(self):
        sa=[{'date':'2026-08-01','value':100},{'date':'2026-09-01','value':110},{'date':'2026-10-01','value':121}]
        nsa=[{'date':'2025-09-01','value':100},{'date':'2025-10-01','value':100},{'date':'2026-09-01','value':102},{'date':'2026-10-01','value':106}]
        m=ppi_measurement(sa,nsa)
        self.assertEqual((m['mom'],m['previous_mom'],m['yoy'],m['previous_yoy']),(10,10,6,2))
        missing=ppi_measurement([sa[0],sa[2]],nsa[:-1])
        self.assertIsNone(missing['mom']);self.assertIsNone(missing['yoy'])

    def test_bls_rejects_failed_api_and_skips_annual_future_and_invalid_values(self):
        with self.assertRaises(FeedError):bls_rows({'status':'REQUEST_FAILED'},'S')
        rows=[{'year':2026,'period':m,'value':v} for m,v in [('M10','120'),('M11','130'),('M13','150'),('M09','NaN'),('M08','0')]]
        p={'status':'REQUEST_SUCCEEDED','Results':{'series':[{'seriesID':'S','data':rows}]}}
        self.assertEqual(len(bls_rows(p,'S',datetime(2026,11,20,tzinfo=timezone.utc))),1)

    def test_ism_headline_is_not_supplier_delivery_and_previous_is_same_index(self):
        html='<h1>Services PMI® at 54.5%</h1><h2>October 2026 ISM® Services PMI® Report</h2><p>Supplier Deliveries Index at 56.7%</p><p>The Services PMI® registered 54.5 percent, a decrease compared to September’s figure of 54.9 percent.</p>'
        m=parse_ism(html,'services',datetime(2026,11,21,tzinfo=timezone.utc))['metric']
        self.assertEqual((m['value'],m['previous'],m['period']),(54.5,54.9,'2026-10'))
        with self.assertRaises(FeedError):parse_ism('<h1>Verify you are human</h1>','services')

    def test_unreachable_or_regressed_ism_does_not_become_live_or_zero(self):
        result=activity_metrics({'macro:pmi_services':{'error':'HTTP 403','checked_at':123}})
        self.assertTrue(result['services']['snapshot']);self.assertGreater(result['services']['value'],0)
        self.assertEqual(result['services']['last_checked'],123)
        result=activity_metrics({'macro:pmi_services':{'data':{'metric':{'period':'2025-01','value':40}}}})
        self.assertIn('较新快照',result['services']['connection_error'])

    def test_assessment_separates_levels_trends_and_price_deflation(self):
        self.assertIn('扩张',activity_assessment({'value':54,'previous':55},'services')['label'])
        self.assertIn('回落',activity_assessment({'value':54,'previous':55},'services')['label'])
        self.assertIn('分界',activity_assessment({'value':50},'manufacturing')['label'])
        self.assertIn('降幅收窄',activity_assessment({'mom':-.2,'previous_mom':-.4},'ppi')['label'])

    def test_free_assistant_answers_economic_and_speech_prompts(self):
        c={'activity':activity_metrics({}),'speeches':[]}
        result=answer_question('PPI和PMI强不强？',c)
        self.assertIn('ISM',result);self.assertIn('本轮未核验',result);self.assertIn('不宣称',result)
        self.assertIn('还未取得',answer_question('美联储最近说了什么？',c))


class SpeechTests(unittest.TestCase):
    def test_official_source_boundary_and_short_dates(self):
        self.assertTrue(source_url('https://www.newyorkfed.org/newsevents/speeches/2026/wil261119','https://www.newyorkfed.org/newsevents/speeches'))
        self.assertFalse(source_url('https://newyorkfed.org.evil.test/a','https://www.newyorkfed.org'))
        self.assertFalse(source_url('https://a:b@www.newyorkfed.org/a','https://www.newyorkfed.org'))
        self.assertTrue(guessed_date('https://www.newyorkfed.org/newsevents/speeches/2026/wil261119').startswith('2026-11-19'))
        self.assertTrue(guessed_date('https://www.philadelphiafed.org/the-economy/monetary-policy/261119-remarks').startswith('2026-11-19'))
        self.assertEqual(prose_date('Speech on November 18, 2026'),'2026-11-18')

    def test_negation_and_supply_demand_tradeoff_are_not_hawk_votes(self):
        s=speech_summary('We do not plan to raise interest rates. A supply shock differs from a demand shock.','')
        self.assertEqual(s['stance'],'未识别明确利率方向');self.assertIn('供给冲击',s['summary'])
        s=speech_summary('Inflation remains too high. Further tightening may be needed, but uncertainty remains.','')
        self.assertEqual(s['stance'],'偏鹰线索');self.assertLessEqual(len(s['evidence'][0].replace(' …','').split()),20)

    def test_rss_drops_future_and_nonofficial_articles(self):
        now=datetime.now(timezone.utc);old=(now-timedelta(days=1)).isoformat();future=(now+timedelta(days=2)).isoformat()
        xml=f'<rss><channel><item><title>Cook, remarks</title><link>https://www.federalreserve.gov/a</link><pubDate>{old}</pubDate></item><item><link>https://www.federalreserve.gov/future</link><pubDate>{future}</pubDate></item><item><link>https://other.example/a</link><pubDate>{old}</pubDate></item></channel></rss>'
        rows=rss_speeches(xml,'https://www.federalreserve.gov/feeds/a.xml')
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['speaker'],'Cook')

    def test_body_failure_is_explicit_not_a_fake_full_summary(self):
        date=(datetime.now(timezone.utc)-timedelta(days=1)).isoformat()
        xml=f'<rss><channel><item><title>Cook, remarks</title><link>https://www.federalreserve.gov/newsevents/speech/a.htm</link><pubDate>{date}</pubDate></item></channel></rss>'.encode()
        with patch('gold_intelligence.speeches.get_bytes',return_value=xml),patch('gold_intelligence.speeches.article_details',side_effect=FeedError('blocked')):
            item=fetch_speeches('board')['items'][0]
        self.assertFalse(item['full_text_obtained']);self.assertEqual(item['body_error'],'blocked');self.assertIn('未取得正文',item['summary'])


class MessageAndJournalTests(unittest.TestCase):
    def message(self,title='Oil supply disrupted',url='https://example.com/a'):
        return {'title':title,'url':url,'date':datetime.now(timezone.utc).isoformat(),'source':'fixture'}

    def payload(self):
        m=self.message();m['key']=message_key(m)
        return {'reference_date':'2026-11-19','model_generated_at':'a','forecast_rows':[{'h':7,'date':'2026-11-30','center':3000,'low80':2900,'high80':3100}],'messages':[m]}

    def test_word_boundaries_energy_and_ceasefire_counterchannels(self):
        self.assertNotIn('冲突',classify_news({'title':'Warsh gives opening remarks'})[0])
        self.assertEqual(analyze_message(self.message('Ceasefire after missile attack'))['category'],'地缘缓和')
        self.assertEqual(analyze_message(self.message())['category'],'能源/供给冲击')
        self.assertEqual(analyze_message(self.message('Political turmoil'))['category'],'一般宏观/黄金新闻')

    def test_tracking_urls_deduplicate_and_future_or_old_news_is_not_recent(self):
        m=self.message();duplicate={**m,'url':m['url']+'?utm_source=rss#part','full_text_obtained':True}
        future={**m,'url':'https://example.com/b','date':(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()}
        old={**m,'url':'https://example.com/c','date':(datetime.now(timezone.utc)-timedelta(days=8)).isoformat()}
        rows=recent_messages([m,future,old],[duplicate])
        self.assertEqual(len(rows),1);self.assertTrue(rows[0]['full_text_obtained'])

    def test_zero_stress_preserves_forecast_and_directional_stress_does_not_claim_coverage(self):
        fc={'vol':.01,'rows':[{'h':7,'low80':2900,'high80':3100}]}
        for s in ('baseline','pressure','support','energy','geopolitics'):
            r=stress_range(fc,7,s,0);self.assertEqual((r['low'],r['high']),(2900,3100))
        r=stress_range(fc,7,'pressure',1);self.assertLess(r['low'],2900);self.assertEqual(r['high'],3100)
        r=stress_range(fc,7,'energy',1);self.assertGreater(r['high'],3100);self.assertIn('无统计覆盖率',r['classification'])
        with self.assertRaises(ValueError):stress_range(fc,7,'energy',float('nan'))
        self.assertEqual(fc['rows'][0]['low80'],2900)

    def test_journal_restarts_deduplicates_and_distinguishes_revisions_from_rolling_dates(self):
        with tempfile.TemporaryDirectory() as folder:
            now=[100.];path=Path(folder)/'journal.db';j=AnalysisJournal(path,clock=lambda:now[0]);p=self.payload()
            first=j.capture(p);self.assertTrue(first['diff']['first'])
            changed_time={**p,'model_generated_at':'b'};self.assertFalse(j.capture(changed_time)['wrote'])
            p2=deepcopy(p);p2['forecast_rows'][0]['center']=3010
            self.assertTrue(j.capture(p2,allow_write=False,force=True)['pending'])
            now[0]=200.;second=j.capture(p2)
            self.assertEqual(second['diff']['range_changes'][0]['change'],10)
            restored=AnalysisJournal(path,clock=lambda:300.)
            self.assertEqual(len(restored.history()),2)
            p3=deepcopy(p2);p3['forecast_rows'][0]['date']='2026-12-01'
            p3['messages'][0]['title']='Updated title'
            r=restored.capture(p3)
            self.assertIsNone(r['diff']['range_changes'][0]['change'])
            self.assertEqual(len(r['diff']['new']),0);self.assertEqual(len(r['diff']['revised']),1)
            self.assertEqual(len(restored.archived_messages()),1)

    def test_public_snapshot_does_not_serialize_chat_or_stress_inputs(self):
        context={'readiness':{},'forecast':None,'activity':{},'messages':[],'chat':[{'secret':'private'}],'stress_multiple':1}
        p=snapshot_payload(context)
        self.assertNotIn('chat',p);self.assertNotIn('stress_multiple',p)


if __name__=='__main__':unittest.main()
