from datetime import datetime,timedelta,timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import streamlit as st
from streamlit.testing.v1 import AppTest
from gold_intelligence.feeds import FeedError
from gold_intelligence.service import DataHub,default_specs
from gold_intelligence.yields import clean_rows,parse_h15,parse_rate_csv,rate_summary,resolve_rates


def table(rows):
    return '<table>'+''.join('<tr>'+''.join(f'<td>{cell}</td>' for cell in row)+'</tr>' for row in rows)+'</table>'


class YieldTests(unittest.TestCase):
    def test_h15_distinguishes_real_and_nominal_and_skips_closed_day(self):
        body=table([['Instruments','2026Nov11*','2026Nov12','2026Nov13','2026Nov16','2026Nov17'],
            ['10-year','99','99','99','99','99'],['Treasury constant maturities','','','','',''],
            ['Nominal 9','','','','',''],['2-year','','4.86','4.88','4.83','4.80'],
            ['10-year','','5.10','5.15','5.12','5.10'],['Inflation indexed 10','','','','',''],
            ['10-year','','2.86','2.91','2.92','2.89']])
        parsed=parse_h15(body)
        self.assertEqual(len(parsed['series']['DFII10']),4)
        self.assertEqual(parsed['series']['DFII10'][-1]['value'],2.89)
        self.assertEqual(parsed['series']['DGS2'][-1]['value'],4.80)
        self.assertEqual(parsed['series']['DGS10'][-1]['value'],5.10)
        self.assertNotIn('2026-11-11',[r['date'] for r in parsed['series']['DFII10']])
        with self.assertRaises(FeedError):parse_h15('<html>Access denied</html>')

    def test_single_csv_allows_negative_and_zero_real_yields(self):
        result=parse_rate_csv(b'observation_date,DFII10\n2026-11-12,-0.02\n2026-11-13,.\n2026-11-16,0\n2026-11-17,NaN\n', 'DFII10')
        self.assertEqual([r['value'] for r in result['series']['DFII10']],[-.02,0.])
        self.assertEqual(rate_summary(result['series']['DFII10'])['change_bp'],2.)
        with self.assertRaises(FeedError):parse_rate_csv(b'DATE,DGS2\n2026-11-17,4.8\n','DFII10')

    def test_changes_are_basis_points_between_valid_observations(self):
        rows=[{'date':'2026-11-17','value':2.89},{'date':'2026-11-13','value':2.91},
              {'date':'2026-11-16','value':2.92},{'date':'2026-11-14','value':None}]
        info=rate_summary(rows)
        self.assertAlmostEqual(info['change_bp'],-3)
        self.assertEqual(info['direction'],'下降')
        self.assertEqual(info['previous_date'],'2026-11-16')
        self.assertIsNone(info['change5_bp'])
        one=rate_summary([rows[0]])
        self.assertIsNone(one['change_bp'])
        same=rate_summary([{'date':'2026-11-16','value':2.89},rows[0]])
        self.assertEqual(same['direction'],'持平')
        self.assertEqual(same['change_bp'],0.)

    def test_five_observation_change_is_not_relative_percent(self):
        rows=[{'date':f'2026-11-{i+1:02}','value':2.+i*.01} for i in range(6)]
        self.assertAlmostEqual(rate_summary(rows)['change5_bp'],5)
        self.assertEqual(rate_summary(rows)['direction'],'上升')

    def test_sources_merge_chronologically_with_per_observation_provenance(self):
        feeds={'macro':{'fetched_at':50,'data':{'series':{'DFII10':[{'date':'2026-11-16','value':2.90}]},'source':'FRED'}},
               'rates:h15':{'fetched_at':100,'data':{'series':{'DFII10':[{'date':'2026-11-16','value':2.92},{'date':'2026-11-17','value':2.89}]},'source':'H15'}},
               'rates:DFII10':{'fetched_at':10,'data':{'series':{'DFII10':[{'date':'2026-11-16','value':99}]},'source':'old'}}}
        result=resolve_rates(feeds)['DFII10']
        self.assertEqual([r['value'] for r in result],[2.92,2.89])
        self.assertEqual(result[-1]['source'],'H15')
        self.assertEqual(resolve_rates({})['DGS2'],[])

    def test_rate_cards_render_even_when_main_macro_download_failed(self):
        with tempfile.TemporaryDirectory() as directory:
            hub=DataHub(directory)
            for entry in hub._entries.values():entry['next_attempt']=float('inf')
            hub._entries['rates:h15'].update(fetched_at=datetime.now(timezone.utc).timestamp(),data={
                'series':{'DFII10':[{'date':'2026-11-16','value':2.92},{'date':'2026-11-17','value':2.89}],
                          'DGS2':[{'date':'2026-11-16','value':4.83},{'date':'2026-11-17','value':4.80}],
                          'DGS10':[{'date':'2026-11-16','value':5.12},{'date':'2026-11-17','value':5.10}]},
                'source':'美联储 H.15 官方日度发布','url':'https://www.federalreserve.gov/releases/h15/'})
            try:
                st.cache_resource.clear()
                with patch('gold_intelligence.service.DataHub',return_value=hub):
                    app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py')).run(timeout=20)
                self.assertEqual(len(app.exception),0,str(app.exception))
                metrics={m.label:m.value for m in app.metric}
                self.assertEqual(metrics['10年期实际收益率'],'2.89%')
                self.assertEqual(metrics['2年期美债收益率（名义）'],'4.80%')
                self.assertIn('美债收益率 · 上升与下降',' '.join(m.value for m in app.markdown))
            finally:
                hub.close();st.cache_resource.clear()


if __name__=='__main__':unittest.main()
