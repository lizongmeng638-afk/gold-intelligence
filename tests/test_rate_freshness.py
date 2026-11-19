from datetime import datetime,timezone
from zoneinfo import ZoneInfo
import tempfile
import unittest
from unittest.mock import patch
from xml.etree.ElementTree import Element,SubElement,tostring

from gold_intelligence.feeds import FeedError
from gold_intelligence.service import DataHub,FeedSpec
from gold_intelligence.yields import parse_treasury_xml,merge_rate_payload,resolve_rates
from gold_intelligence.rate_freshness import expected_observation_date,rate_freshness
from test_collection import settle

NY=ZoneInfo('America/New_York')
UTC=timezone.utc


def xml(kind,rows):
    root=Element('feed')
    for date,value in rows:
        e=SubElement(root,'entry');SubElement(e,'updated').text='2026-11-19T01:02:36Z'
        props=SubElement(SubElement(e,'content'),'properties')
        SubElement(props,'NEW_DATE').text=date+'T00:00:00'
        SubElement(props,'TC_10YEAR' if kind=='real' else 'BC_2YEAR').text=value
        if kind=='nominal':SubElement(props,'BC_10YEAR').text='5.07'
    return tostring(root)


class FreshnessTests(unittest.TestCase):
    def now(self):return datetime(2026,11,19,10,tzinfo=NY)

    def test_treasury_real_and_nominal_fields_and_update_metadata(self):
        real=parse_treasury_xml(xml('real',[('2026-11-18','2.88'),('2026-11-17','2.89')]),'real')
        self.assertEqual(real['series']['DFII10'][-1]['value'],2.88)
        self.assertTrue(real['series']['DFII10'][-1]['source_updated_at'].startswith('2026-11-19T01:02:36'))
        nominal=parse_treasury_xml(xml('nominal',[('2026-11-18','4.80')]),'nominal')
        self.assertEqual(nominal['series']['DGS2'][-1]['value'],4.8)
        self.assertEqual(nominal['series']['DGS10'][-1]['value'],5.07)
        with self.assertRaises(FeedError):parse_treasury_xml(b'<html>blocked</html>','real')

    def test_current_month_network_failure_is_not_hidden_as_old_month_success(self):
        from gold_intelligence.yields import fetch_treasury
        with patch('gold_intelligence.yields.get_bytes',side_effect=FeedError('连接超时')) as fetch:
            with self.assertRaises(FeedError):fetch_treasury('nominal')
            self.assertEqual(fetch.call_count,1)

    def test_expected_date_before_after_cutoff_weekend_holiday_and_dst(self):
        self.assertEqual(str(expected_observation_date(self.now())),'2026-11-18')
        self.assertEqual(str(expected_observation_date(datetime(2026,11,19,17,1,tzinfo=NY))),'2026-11-19')
        self.assertEqual(str(expected_observation_date(datetime(2026,11,21,12,tzinfo=NY))),'2026-11-20')
        self.assertEqual(str(expected_observation_date(datetime(2026,12,25,18,tzinfo=NY))),'2026-12-24')
        self.assertEqual(str(expected_observation_date(datetime(2026,7,7,20,59,tzinfo=UTC))),'2026-07-06')
        self.assertEqual(str(expected_observation_date(datetime(2026,7,7,21,1,tzinfo=UTC))),'2026-07-07')

    def test_new_download_of_old_observation_is_not_called_current(self):
        now=self.now();rows=[{'date':'2026-11-17','value':2.89,'fetched_at':now.timestamp()}]
        feeds={'rates:h15':{'checked_at':now.timestamp(),'ttl':900,'data':{'series':{'DFII10':rows}}}}
        status=rate_freshness(rows,feeds,'DFII10',now)
        self.assertEqual(status['state'],'possibly_delayed')
        self.assertIsNone(status['is_delayed'])
        self.assertEqual(status['expected_date'],'2026-11-18')

    def test_recent_verified_official_day_is_current_but_not_today_intraday(self):
        now=self.now();rows=[{'date':'2026-11-18','value':2.88,'fetched_at':now.timestamp()-10}]
        feeds={'rates:treasury_real':{'checked_at':now.timestamp(),'ttl':900,'data':{'series':{'DFII10':rows}}}}
        result=rate_freshness(rows,feeds,'DFII10',now)
        self.assertFalse(result['is_delayed'])
        self.assertEqual(result['state'],'current')
        feeds['rates:treasury_real']['checked_at']=now.timestamp()-901
        self.assertEqual(rate_freshness(rows,feeds,'DFII10',now)['state'],'unverified')

    def test_failed_check_does_not_make_cached_data_fresh(self):
        now=self.now();rows=[{'date':'2026-11-18','value':2.88,'fetched_at':now.timestamp()-3600}]
        feeds={'rates:treasury_real':{'checked_at':now.timestamp(),'error':'timeout','ttl':900,'data':{'series':{'DFII10':rows}}}}
        result=rate_freshness(rows,feeds,'DFII10',now)
        self.assertEqual(result['state'],'failed')
        self.assertEqual(result['data_fetched_at'],now.timestamp()-3600)
        self.assertIsNone(result['is_delayed'])

    def test_macro_six_hour_ttl_cannot_hide_expired_yield_check(self):
        now=self.now();rows=[{'date':'2026-11-18','value':2.88}]
        feeds={'macro':{'fetched_at':now.timestamp()-3600,'ttl':21600,'data':{'series':{'DFII10':rows}}}}
        self.assertEqual(rate_freshness(rows,feeds,'DFII10',now)['state'],'unverified')

    def test_source_regression_preserves_newer_date_and_original_fetch_time(self):
        previous={'series':{'DFII10':[{'date':'2026-11-18','value':2.88}]},'source':'treasury'}
        incoming={'series':{'DFII10':[{'date':'2026-11-17','value':2.89}]},'source':'treasury'}
        result=merge_rate_payload(previous,incoming,1000,2000)
        self.assertEqual(result['observed_at'],'2026-11-18')
        self.assertEqual(result['checked_latest_dates']['DFII10'],'2026-11-17')
        self.assertEqual(result['source_regressed'],['DFII10'])
        self.assertEqual(result['series']['DFII10'][-1]['fetched_at'],1000)
        resolved=resolve_rates({'rates:treasury_real':{'data':result,'fetched_at':2000}})['DFII10']
        self.assertEqual(resolved[-1]['fetched_at'],1000)
        self.assertEqual(resolved[-1]['date'],'2026-11-18')

    def test_hub_successful_older_payload_cannot_replace_later_cached_observation(self):
        clock=[1000.];payloads=[{'series':{'DFII10':[{'date':'2026-11-18','value':2.88}]}},
            {'series':{'DFII10':[{'date':'2026-11-17','value':2.89}]}}]
        with tempfile.TemporaryDirectory() as folder:
            hub=DataHub(folder,[FeedSpec('rates:DFII10','rate',60,lambda:payloads.pop(0))],clock=lambda:clock[0])
            try:
                hub.refresh_due();settle(hub);clock[0]+=61;hub.refresh_due();settle(hub)
                result=hub.snapshot()['feeds']['rates:DFII10']
                self.assertEqual(result['data']['observed_at'],'2026-11-18')
                self.assertIn('较旧',result['status'])
                self.assertEqual(result['checked_at'],1061.)
            finally:hub.close()


if __name__=='__main__':unittest.main()
