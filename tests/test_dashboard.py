from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
import streamlit as st
from streamlit.testing.v1 import AppTest

from gold_intelligence.models import forecast_model
from gold_intelligence.service import DataHub, FeedSpec

BASE=Path(__file__).resolve().parents[1]


class DashboardTests(unittest.TestCase):
    def test_forecast_intervals_and_trading_day_dates(self):
        rng=np.random.default_rng(42)
        index=pd.bdate_range(end=pd.Timestamp.now().normalize(),periods=300)
        gold=pd.Series(2000*np.exp(np.cumsum(rng.normal(0,.01,len(index)))),index=index)
        market=pd.DataFrame({'Gold':gold,'DXY':100*np.exp(np.cumsum(rng.normal(0,.001,len(index))))})
        result=forecast_model(market,{},float(gold.iloc[-1]))
        self.assertIsNotNone(result)
        for row in result['rows']:
            self.assertLess(row['low95'],row['low80'])
            self.assertLess(row['low80'],row['center'])
            self.assertLess(row['center'],row['high80'])
            self.assertLess(row['high80'],row['high95'])
            self.assertAlmostEqual(row['up']+row['down']+row['flat'],1)
            self.assertLess(row['date'].weekday(),5)

    def test_empty_feeds_do_not_block_macro_and_news_sections(self):
        with tempfile.TemporaryDirectory() as folder:
            from gold_intelligence.service import default_specs
            def fail():
                raise RuntimeError('offline')
            specs=[FeedSpec(s.key,s.label,s.ttl,fail,s.host) for s in default_specs()]
            hub=DataHub(folder,specs)
            try:
                st.cache_resource.clear()
                with patch('gold_intelligence.service.DataHub',return_value=hub):
                    at=AppTest.from_file(str(BASE/'app.py')).run(timeout=15)
                self.assertEqual(len(at.exception),0, str(at.exception))
                text=' '.join(x.value for x in at.markdown)
                self.assertIn('美联储讲话、能源与地缘消息',text)
                self.assertIn('美国宏观经济指标',text)
                self.assertGreaterEqual(len(at.dataframe),2)
            finally:
                hub.close()
                st.cache_resource.clear()

    def test_full_live_cache_renders_quote_forecast_macro_and_news(self):
        # A live cache is created by the diagnostic script; this test is skipped
        # in a fresh user checkout and never makes network calls.
        cache=BASE/'data'/'cache'
        if not cache.exists():
            self.skipTest('no live diagnostic cache')
        hub=DataHub(cache)
        for e in hub._entries.values():
            e['next_attempt']=float('inf')
        try:
            st.cache_resource.clear()
            with patch('gold_intelligence.service.DataHub',return_value=hub):
                at=AppTest.from_file(str(BASE/'app.py')).run(timeout=20)
            self.assertEqual(len(at.exception),0,str(at.exception))
            labels=[x.label for x in at.metric]
            self.assertIn('黄金现货参考 / USD每盎司',labels)
            self.assertIn('中心情景价',labels)
            self.assertIn('重要因子提醒',' '.join(x.value for x in at.markdown))
            self.assertGreaterEqual(len(at.dataframe),3)
        finally:
            hub.close()
            st.cache_resource.clear()


if __name__=='__main__':
    unittest.main()
