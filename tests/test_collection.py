import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from zipfile import ZipFile
from datetime import datetime, timezone

from gold_intelligence.feeds import FeedError, fetch_gdelt, normalize_news, parse_fred, parse_market, parse_time
from gold_intelligence.service import DataHub, FeedSpec


def settle(hub):
    end = time.monotonic()+3
    while any(e['running'] for e in hub.snapshot()['feeds'].values()):
        if time.monotonic() > end:
            raise AssertionError('background jobs did not finish')
        time.sleep(.005)


class CollectionTests(unittest.TestCase):
    def test_render_is_nonblocking_and_jobs_are_deduplicated(self):
        release = threading.Event()
        entered = threading.Event()
        calls = []
        def slow():
            calls.append(1)
            entered.set()
            release.wait(2)
            return {'price':1}
        with tempfile.TemporaryDirectory() as folder:
            hub = DataHub(folder,[FeedSpec('slow','slow',60,slow),FeedSpec('fast','fast',60,lambda:{'price':2})],workers=2)
            try:
                start = time.monotonic()
                self.assertEqual(hub.refresh_due(),2)
                self.assertLess(time.monotonic()-start,.2)
                entered.wait(1)
                self.assertEqual(hub.refresh_due(force=True),0)
                for _ in range(100):
                    if hub.snapshot()['feeds']['fast']['data']:
                        break
                    time.sleep(.005)
                self.assertEqual(hub.snapshot()['feeds']['fast']['data']['price'],2)
                self.assertTrue(hub.snapshot()['feeds']['slow']['running'])
            finally:
                release.set()
                hub.close()
            self.assertEqual(len(calls),1)

    def test_cache_survives_restart_and_failed_refresh(self):
        clock = [1000.]
        with tempfile.TemporaryDirectory() as folder:
            hub = DataHub(folder,[FeedSpec('quote','quote',60,lambda:{'price':123})],clock=lambda:clock[0])
            hub.refresh_due(); settle(hub); hub.close()
            clock[0] += 61
            def fail():
                raise FeedError('timeout')
            hub = DataHub(folder,[FeedSpec('quote','quote',60,fail)],clock=lambda:clock[0])
            try:
                before = hub.snapshot()['feeds']['quote']
                self.assertEqual(before['data']['price'],123)
                self.assertTrue(before['from_disk'])
                hub.refresh_due(); settle(hub)
                after = hub.snapshot()['feeds']['quote']
                self.assertEqual(after['data']['price'],123)
                self.assertEqual(after['fetched_at'],1000.)
                self.assertIn('缓存',after['status'])
                self.assertEqual(hub.refresh_due(force=True),0)
            finally:
                hub.close()

    def test_rate_limit_retry_after_is_honored(self):
        clock=[1000.]
        def fail():
            raise FeedError('HTTP 429',retry_after=120)
        with tempfile.TemporaryDirectory() as folder:
            hub=DataHub(folder,[FeedSpec('x','x',60,fail)],clock=lambda:clock[0])
            try:
                hub.refresh_due(); settle(hub)
                clock[0]+=60
                self.assertEqual(hub.refresh_due(force=True),0)
                self.assertEqual(hub.snapshot()['feeds']['x']['retry_in'],60)
                clock[0]+=61
                self.assertEqual(hub.refresh_due(),1)
                settle(hub)
            finally:
                hub.close()

    def test_corrupt_cache_is_ignored(self):
        with tempfile.TemporaryDirectory() as folder:
            spec=FeedSpec('x','x',60,lambda:{'ok':True})
            hub=DataHub(folder,[spec]); hub._path('x').write_text('{broken'); hub.close()
            hub=DataHub(folder,[spec])
            try:
                self.assertIsNone(hub.snapshot()['feeds']['x']['data'])
                hub.refresh_due(); settle(hub)
                self.assertEqual(hub.snapshot()['feeds']['x']['data'],{'ok':True})
            finally:
                hub.close()

    def test_partial_macro_does_not_delete_previous_series(self):
        clock=[1000.]
        responses=[{'series':{'DFII10':[1],'PAYEMS':[2]},'series_fetched':{'DFII10':'old','PAYEMS':'old'},'missing':[]},
                   {'series':{'DFII10':[3]},'series_fetched':{'DFII10':'new'},'missing':['PAYEMS']}]
        with tempfile.TemporaryDirectory() as folder:
            hub=DataHub(folder,[FeedSpec('macro','macro',60,lambda:responses.pop(0))],clock=lambda:clock[0])
            try:
                hub.refresh_due(); settle(hub); clock[0]+=61
                hub.refresh_due(); settle(hub)
                data=hub.snapshot()['feeds']['macro']['data']
                self.assertEqual(data['series'],{'DFII10':[3],'PAYEMS':[2]})
                self.assertEqual(data['series_fetched']['PAYEMS'],'old')
                self.assertIn('部分',hub.snapshot()['feeds']['macro']['status'])
            finally:
                hub.close()

    def test_mixed_frequency_fred_zip_and_missing_values(self):
        date=datetime.now(timezone.utc).date().isoformat()
        blob=io.BytesIO()
        with ZipFile(blob,'w') as z:
            z.writestr('daily.csv',f'observation_date,DFII10,DGS10\n{date},1.2,.\n')
            z.writestr('monthly.csv',f'observation_date,PAYEMS\n{date},150000\n')
        data=parse_fred(blob.getvalue())
        self.assertEqual(data['series']['DFII10'][0]['value'],1.2)
        self.assertEqual(data['series']['PAYEMS'][0]['value'],150000)
        self.assertIn('DGS10',data['missing'])
        with self.assertRaises(FeedError):
            parse_fred(b'<html>Access denied</html>')

    def test_gdelt_timestamp_dedup_and_unsafe_urls(self):
        date='20261116T123000Z'
        items=normalize_news([{'title':'Gold update','url':'https://example.com/a','date':date},
                              {'title':'gold UPDATE','url':'https://example.com/b','date':date},
                              {'title':'bad','url':'javascript:alert(1)','date':date}])
        self.assertEqual(len(items),1)
        self.assertEqual(parse_time(items[0]['date']).hour,12)
        self.assertEqual(parse_time('20261116123000').minute,30)

    def test_gdelt_error_is_not_cached_as_successful_empty_news(self):
        with patch('gold_intelligence.feeds.get_json',return_value={'error':'bad query'}):
            with self.assertRaises(FeedError):
                fetch_gdelt()

    def test_yahoo_rate_limit_falls_back_without_erasing_backoff(self):
        from gold_intelligence.feeds import fetch_market
        expected = {'ticker':'GC=F','rows':[{'date':'2026-11-19','value':800}]}
        with patch('gold_intelligence.feeds.get_json',side_effect=FeedError('HTTP 429',120)), patch('gold_intelligence.feeds._fetch_market_yfinance',return_value=expected):
            self.assertEqual(fetch_market('GC=F'),expected)
        with patch('gold_intelligence.feeds.get_json',side_effect=FeedError('HTTP 429',120)), patch('gold_intelligence.feeds._fetch_market_yfinance',side_effect=RuntimeError('limited')):
            with self.assertRaises(FeedError) as result:
                fetch_market('GC=F')
            self.assertEqual(result.exception.retry_after,120)

    def test_market_symbol_validation_and_nonfinite_values(self):
        stamp=int(time.time())-86400
        item={'meta':{'symbol':'GC=F'},'timestamp':[stamp,stamp+1,stamp+2],
              'indicators':{'quote':[{'close':[2000,None,float('nan')]}]}}
        result=parse_market({'chart':{'result':[item]}},'GC=F')
        self.assertEqual(len(result['rows']),1)
        self.assertEqual(result['instrument'],'futures')
        with self.assertRaises(FeedError):
            parse_market({'chart':{'result':[item]}},'XAUUSD=X')


if __name__=='__main__':
    unittest.main()
