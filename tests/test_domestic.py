from datetime import datetime,timedelta
import unittest
from gold_intelligence.domestic import HIGH,LOW,MID,TZ,comparable,parse_retail,parse_sge
from gold_intelligence.feeds import FeedError


def table(rows):
    return '<table>'+''.join('<tr>'+''.join(f'<td>{v}</td>' for v in row)+'</tr>' for row in rows)+'</table>'


class DomesticTests(unittest.TestCase):
    def quote(self,price):
        return dict(channel='甲',product='黄金',category='品牌金饰',purity='成色未注明',side='买入',price=price,date='2026-11-19',source_kind='公开挂牌')

    def test_sge_uses_close_column_and_filters_other_contracts(self):
        day=str(datetime.now(TZ).date())
        result=parse_sge(table([[day,'Au99.99','810','840','800','825','15'],[day,'Au(T+D)','1','2','3','999','1'],[day,'Au99.99','1','2','3','-','1']]))
        self.assertEqual(result['rows'],[{'date':day,'value':825.}])
        with self.assertRaises(FeedError):parse_sge('<html>网络错误</html>')

    def test_retail_filters_other_metals_and_distinguishes_product_and_purity(self):
        day=str(datetime.now(TZ).date())
        result=parse_retail(table([['甲','首饰黄金','1151',day],['乙','投资金条','1010',day],['丙','999黄金','1129',day],['丁','黄金回收','790',day],['丁','黄金换新','973',day],['乙','白银','15',day],['乙','PT950铂金','550',day],['无效','黄金','NaN',day]]))
        self.assertEqual(len(result['quotes']),5)
        self.assertEqual(result['quotes'][1]['category'],'投资黄金/金条')
        self.assertEqual(result['quotes'][2]['purity'],'999足金')
        self.assertEqual(result['quotes'][3]['side'],'卖出')
        with self.assertRaises(FeedError):parse_retail('<html>登录</html>')

    def test_low_high_ties_and_only_comparable_rows(self):
        rows=[self.quote(100),self.quote(100),self.quote(120),self.quote(110)]
        for field,value in [('date','2026-11-18'),('category','投资黄金/金条'),('purity','999足金'),('source_kind','手动录入')]:
            row=self.quote(1);row[field]=value;rows.append(row)
        result=comparable(rows,'品牌金饰','成色未注明','2026-11-19','买入')
        self.assertEqual([r['price'] for r in result],[100,100,110,120])
        self.assertEqual([r['color'] for r in result],[LOW,LOW,MID,HIGH])
        self.assertEqual(result[-1]['difference'],20)

    def test_single_or_equal_prices_do_not_claim_unique_cheapest(self):
        one=comparable([self.quote(100)],'品牌金饰','成色未注明','2026-11-19')
        self.assertEqual(one[0]['marker'],'仅一条报价')
        same=comparable([self.quote(100),self.quote(100)],'品牌金饰','成色未注明','2026-11-19')
        self.assertTrue(all(r['marker']=='同价' for r in same))

    def test_bank_same_side_and_fifteen_minute_window(self):
        now=datetime.now(TZ);rows=[]
        for price,minutes,side in [(100,0,'买入'),(80,16,'买入'),(101,5,'买入'),(50,0,'卖出')]:
            row=self.quote(price);row.update(source_kind='手动录入',quoted_at=(now-timedelta(minutes=minutes)).isoformat(),side=side);rows.append(row)
        result=comparable(rows,'品牌金饰','成色未注明','2026-11-19','买入','手动录入')
        self.assertEqual([r['price'] for r in result],[100,101])


if __name__=='__main__':unittest.main()
