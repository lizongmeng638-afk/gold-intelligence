from datetime import datetime, timezone
import unittest
from unittest.mock import patch

from gold_intelligence.feeds import FeedError
from gold_intelligence.gold_logic import EVENTS
from gold_intelligence.history import bundled_history, choose_history, event_window, fibonacci, parse_monthly, swings, trend_summary
from gold_intelligence.logic_ui import annual_changes, history_chart


class HistoryTests(unittest.TestCase):
    def test_history_complete_and_recent_samples_match_official_pink_sheet(self):
        data=bundled_history()
        self.assertEqual(data['rows'][0],{'date':'1971-01-01','value':38.0})
        lookup={r['date'][:7]:r['value'] for r in data['rows']}
        self.assertEqual([lookup[m] for m in ['2026-08','2026-09','2026-10']],[4411,4319,4105])
        self.assertEqual(len(lookup),670)
        self.assertIn('公开镜像',data['source'])

    def test_monthly_rejects_duplicates_missing_month_nonpositive_future(self):
        from gold_intelligence.history import REFERENCE
        text=(REFERENCE/'gold_monthly.csv').read_text()
        cases=[text+text.splitlines()[1]+'\n',text.replace('1972-01,', 'bad-date,'),
               text.replace('2026-10,4105.000','2026-10,0'),text+'2026-11,4000\n',
               '\n'.join(line for line in text.splitlines() if not line.startswith('1972-01'))]
        for value in cases:
            with self.subTest(value=value[-50:]),self.assertRaises(FeedError):
                parse_monthly(value,datetime(2026,11,20,tzinfo=timezone.utc))

    def test_newer_bundled_history_wins_over_older_download(self):
        old={'data':{'rows':[{'date':'2020-01-01','value':1500}]}}
        self.assertTrue(choose_history(old)['bundled'])

    def test_fibonacci_up_down_and_positive_negative_extensions(self):
        up=[{'date':'2026-01-01','value':100},{'date':'2026-02-01','value':200},{'date':'2026-03-01','value':150}]
        result=fibonacci(up)
        self.assertEqual(result['direction'],'上涨波段')
        self.assertAlmostEqual(result['levels'][4]['value'],138.2)
        self.assertAlmostEqual(result['levels'][-1]['value'],261.8)
        self.assertFalse(result['invalid'])
        down=[dict(r,value=300-r['value']) for r in up]
        result=fibonacci(down)
        self.assertEqual(result['direction'],'下跌波段')
        self.assertAlmostEqual(result['levels'][4]['value'],161.8)
        self.assertAlmostEqual(result['levels'][-1]['value'],38.2)
        with self.assertRaises(ValueError):fibonacci(up,'2026-03-01','2026-01-01')
        with self.assertRaises(ValueError):fibonacci([dict(r,value=100) for r in up])

    def test_fibonacci_invalidation_after_selected_anchor_and_range_break(self):
        rows=[{'date':f'2026-01-0{i+1}','value':p} for i,p in enumerate([100,200,90])]
        result=fibonacci(rows,'2026-01-01','2026-01-02')
        self.assertTrue(result['invalid'])
        self.assertIsNone(result['below'])

    def test_retrospective_swings_have_open_last_leg_and_chronological_extremes(self):
        rows=[{'date':f'2026-{i+1:02d}-01','value':p} for i,p in enumerate([100,110,140,160,120,100,130,125])]
        legs=swings(rows,.2)
        self.assertEqual([(l['a']['value'],l['b']['value']) for l in legs],[(100,160),(160,100),(100,125)])
        self.assertEqual([l['confirmed'] for l in legs],[True,True,False])

    def test_event_window_uses_exact_months_not_nearest_future_and_is_not_causal(self):
        rows=[{'date':f'2020-{i+1:02d}-01','value':100+i*10} for i in range(7)]
        result=event_window(rows,'2020-03-15')
        self.assertEqual(result['a']['date'],'2020-02-01')
        self.assertEqual(result['b']['date'],'2020-06-01')
        self.assertAlmostEqual(result['change'],150/110-1)
        self.assertIsNone(event_window(rows,'2020-06-15'))
        self.assertEqual(len({e['id'] for e in EVENTS}),len(EVENTS))
        self.assertTrue(all(e.get('url','').startswith('https://') and e['counter'] for e in EVENTS))

    def test_annual_partial_period_and_event_marker_price_basis(self):
        rows=[{'date':'2024-12-01','value':100},{'date':'2025-01-01','value':110},{'date':'2025-02-01','value':120}]
        result=annual_changes(rows)
        self.assertEqual(result,[{'year':'2025至02月','change':.19999999999999996,'start':'2024-12','end':'2025-02'}])
        fig=history_chart(rows,[EVENTS[-1]])
        self.assertEqual(list(fig.data[1].x),['2025-02-01'])
        self.assertEqual(list(fig.data[1].y),[120])

    def test_trend_position_uses_current_price_and_complete_lookback(self):
        rows=[{'date':f'2026-01-{i+1:02d}','value':100+i} for i in range(20)]
        trend=trend_summary(rows,3,6,5)
        self.assertEqual(trend['label'],'偏强')
        self.assertAlmostEqual(trend['change'],119/114-1)
        self.assertIsNone(trend_summary(rows,20,50,5))


if __name__=='__main__':unittest.main()
