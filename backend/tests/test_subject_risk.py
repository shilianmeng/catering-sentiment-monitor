"""第 ③ 步·真实数据版：按营业执照主体（统一社会信用代码）给越秀双公示处罚打分排名 + 区域画像；
以及越秀采集器 v2 的大写金额解析。"""
import tempfile
import unittest

import tests  # noqa: F401  先初始化隔离测试库

from app.collectors import yuexiu_sgs as yx
from app.db.session import connect, migrate
from app.engine import store_risk as sr
from app.engine import subject_risk as sj
from app.services import subject_risk_service as svc
from tests import test_api
from tests.test_yuexiu import HONGTAI, JINSHI, FakeSite, fake_detail

AS_OF = "2026-11-23"


def rec(code="91440104MAD3147042", subject="广州某餐饮有限公司", result="罚款5,000元", fine=5000,
        published=AS_OF, dept="广州市越秀区市场监督管理局", wfxw="餐饮服务经营者违法行为", **kw):
    return {"article_title": f"越秀区双公示·行政处罚（统一社会信用代码 {code}）" if code else "越秀区双公示·行政处罚",
            "subject": subject, "investigation_status": "已处罚", "handling_result": result, "fine_amount": fine,
            "published_at": published, "enforcement_dept": dept, "violation_type": wfxw, **kw}


class TestChineseAmounts(unittest.TestCase):
    def test_cn_amount(self):
        for text, v in [("壹仟陆佰壹拾", 1610), ("壹拾肆万零伍佰", 140500), ("叁万伍仟", 35000), ("玖万", 90000),
                        ("三万九千", 39000), ("叁佰伍拾", 350), ("壹仟零伍拾", 1050), ("拾", 10)]:
            self.assertEqual(yx.cn_amount(text), v, text)
        self.assertIsNone(yx.cn_amount("若干"))

    def test_real_decision_wordings(self):
        """2026-11-23 越秀全量数据里漏掉金额的写法，逐种覆盖。"""
        cases = [
            ("罚款人民币壹仟陆佰壹拾元整(￥1610)", 1610),
            ("罚款人民币壹拾肆万零伍佰元整(￥140500)。", 140500),
            ("处罚款人民币叁万伍仟元整(小写:35000元)。", 35000),
            ("罚款人民币伍仟元整", 5000),                                   # 没附小写
            ("罚款人民币肆仟伍佰伍拾?元整(￥4550)", 4550),                   # 原文多了个问号
            ("罚款贰万壹仟元整(￥21000.00元)", 21000),
            ("罚款人民币壹万贰仟圆整(￥12000)、予以关闭。", 12000),
            ("罚款人民币 伍仟元整(￥5000)", 5000),
            ("1.罚款人民币玖万圆整2.责令停业", 90000),
            ("1.没收违法所得:15144元;2.罚款:60576元;罚没款合计:75720元。", 60576),   # 冒号；合计含没收不算罚款
            ("罚款人民币贰仟元整 (￥2000)", 2000),                           # 小写前有空格，不能重复计
        ]
        for text, v in cases:
            self.assertEqual(yx.handling_result("罚款", "决定给予如下行政处罚：" + text)[1], v, text)

    def test_small_written_wins_and_law_text_untouched(self):
        self.assertEqual(yx.handling_result("罚款", "作出如下处罚：罚款人民币伍仟元整(￥5000)")[1], 5000)
        # 法条里「处五万元以上十万元以下罚款」不是本案金额
        law = "作出如下处罚：依据第一百二十二条“并处五万元以上十万元以下罚款”，罚款人民币伍万元整(￥50000)"
        self.assertEqual(yx.handling_result("罚款", law)[1], 50000)
        self.assertIsNone(yx.handling_result("罚款", "作出如下处罚：并处五万元以上十万元以下罚款")[1])

    def test_category_with_comma_not_duplicated(self):
        r, fine = yx.handling_result("其他-责令改正,罚款", "作出如下处罚：罚款人民币肆仟玖佰元整(￥4900)")
        self.assertEqual((r, fine), ("其他-责令改正；罚款4,900元", 4900))

    def test_parser_version_bumped(self):
        self.assertEqual(yx.PARSER_VERSION, 7)

    def test_law_quote_suspend_not_counted(self):
        """Codex 复核 P1：法条复述里的「情节严重的，责令停产停业，直至吊销许可证」不是本案处罚（聚盈/菠萝蜜友/珍珍/御膳居）。"""
        law = ("依据《食品安全法》第一百二十六条“……拒不改正的，处五千元以上五万元以下罚款；情节严重的，"
               "责令停产停业，直至吊销许可证：……”的规定，")
        r, fine = yx.handling_result("罚款", law + "我局决定责令当事人立即改正，并给予当事人一般处罚:处罚款20000元。")
        self.assertEqual(fine, 20000)
        self.assertNotIn("停业", r)
        self.assertNotIn("吊销", r)
        # 没找到决定段落时，不从全文里猜停业/吊销
        self.assertNotIn("停业", yx.handling_result("罚款", law + "罚款20000元。")[0])
        # 决定里真的责令停业 / 吊销的照常记
        self.assertIn("责令停业", yx.handling_result("罚款", law + "本局决定作出如下处罚：1.罚款90000元；2.责令停业。")[0])
        self.assertIn("吊销", yx.handling_result("罚款", law + "本局决定作出如下处罚：吊销食品经营许可证。")[0])

    def test_confiscation_sum_is_not_fine(self):
        """Codex 复核 P1：「罚没款合计」含没收违法所得，不能当罚款（菠萝蜜友 5000 而非 5151，珍珍 2000 而非 2650）。"""
        for text, fine, conf in [
            ("本局决定责令当事人立即改正，并作如下行政处罚:一、没收违法所得151元。二、罚款5000元。罚没款合计5151元。",
             5000, "没收违法所得151元"),
            ("本局决定……具体如下:一、没收工具电磁炉1个;二、没收违法所得650元;三、罚款2000元;罚没款合计2650元。",
             2000, "没收违法所得650元"),
        ]:
            r, f = yx.handling_result("罚款;没收违法所得、没收非法财物", text)
            self.assertEqual(f, fine, text)
            self.assertIn(conf, r)
        # 只写了「合计罚款」的仍以合计为准
        self.assertEqual(yx.handling_result("罚款", "作出如下处罚：罚款3000元；罚款2000元；合计罚款5000元。")[1], 5000)

    def test_trailing_education_is_not_decision_lead(self):
        """Codex 复核：一鼎鲜 564 号末尾「教育如下:」不是决定起点，前面的 200 元罚款不能丢。"""
        text = ("我局决定对当事人……的行为给予罚款200元的行政处罚,并责令当事人立即改正;对当事人未履行……的行为"
                "不予行政处罚,并对当事人教育如下:加强对《中华人民共和国食品安全法》等相关法律法规的学习。")
        self.assertEqual(yx.handling_result("罚款", text)[1], 200)

    def test_confiscation_listed_as_decided(self):
        """Codex 复核：泽楷 419 号「没收违法所得:15144元」要认出金额；类别里的「没收非法财物」决定没列就不写。"""
        text = ("我局决定责令当事人改正上述违法行为,并给予当事人减轻行政处罚如下:1.没收违法所得:15144元;"
                "2.罚款:60576元;罚没款合计:75720元。")
        r, f = yx.handling_result("罚款;没收违法所得、没收非法财物", text)
        self.assertEqual(f, 60576)
        self.assertIn("没收违法所得15,144元", r)
        self.assertNotIn("非法财物", r)
        r, _ = yx.handling_result("罚款;没收违法所得、没收非法财物",
                                  "作出如下处罚：一、没收当事人违法所得6元;二、并处10000元罚款。")
        self.assertIn("没收违法所得6元", r)
        r, _ = yx.handling_result("罚款;没收违法所得、没收非法财物", "作出如下处罚：1.没收涉案舟山眼镜蛇;2.罚款110000元。")
        self.assertIn("没收非法财物", r)


class TestClassify(unittest.TestCase):
    def test_categories(self):
        self.assertEqual(sj.classify(rec()), sj.CAT_FOOD)
        self.assertEqual(sj.classify(rec(dept="广州市越秀区消防救援大队", wfxw="逾期仍不改正")), sj.CAT_FIRE)
        self.assertEqual(sj.classify(rec(dept="广州市越秀区烟草专卖局", wfxw="")), sj.CAT_TOBACCO)
        self.assertEqual(sj.classify(rec(dept="广州市越秀区人力资源和社会保障局", wfxw="逾期仍不改正")), sj.CAT_LABOR)
        self.assertEqual(sj.classify(rec(dept="广州市越秀区人民政府珠光街道办事处", wfxw="超出门窗和外墙设摊经营")),
                         sj.CAT_CITY)
        self.assertEqual(sj.classify(rec(dept="广州市越秀区人民政府珠光街道办事处", wfxw="")), sj.CAT_CITY)
        self.assertEqual(sj.classify(rec(wfxw="注册登记违法行为")), sj.CAT_LICENSE)
        self.assertEqual(sj.classify(rec(wfxw="虚假宣传违法行为(虚假或引人误解的商业宣传)")), sj.CAT_MARKET)
        # 没有 cfWfxw（快照缺失）时退回案情原文
        self.assertEqual(sj.classify(rec(wfxw=None, violation="违反《中华人民共和国食品安全法》")), sj.CAT_FOOD)
        self.assertEqual(sj.classify(rec(wfxw=None, violation="特种设备未登记")), sj.CAT_OTHER)

    def test_category_does_not_change_points(self):
        a = sr.score_official(rec(), AS_OF)
        b = sr.score_official(rec(dept="广州市越秀区消防救援大队"), AS_OF)
        self.assertEqual(a, b)


class TestSubjectScore(unittest.TestCase):
    def test_group_by_credit_code_not_name(self):
        recs = [rec(subject="甲餐饮店", published="2025-11-23"), rec(subject="甲餐饮有限公司"),   # 改名，同一代码
                rec(code="92440101MA5B6QGE6M", subject="甲餐饮店"),                          # 同名不同代码
                rec(code=None, subject="无代码店")]
        ranked = sj.rank(recs, AS_OF)
        self.assertEqual(len(ranked), 3)
        top = ranked[0]
        self.assertEqual((top["credit_code"], top["record_count"]), ("91440104MAD3147042", 2))
        self.assertEqual((top["subject"], top["former_names"]), ("甲餐饮有限公司", ["甲餐饮店"]))
        self.assertIn("name:无代码店", [s["subject_key"] for s in ranked])
        self.assertEqual([s["rank"] for s in ranked], [1, 2, 3])

    def test_score_reuses_store_rules_without_complaints(self):
        s = sj.score_subject([rec(result="罚款100,000元；吊销食品经营许可证", fine=100000)], AS_OF)
        self.assertEqual((s["official_raw"], s["score"], s["level"]), (50.0, 50, "中"))
        self.assertIsNone(s["complaint_score"])
        self.assertIn("暂无", s["complaint_note"])
        many = sj.score_subject([rec(id=i) for i in range(4)], AS_OF)                  # 4×(30+3.5)
        self.assertEqual((many["score"], many["level"]), (70, "高"))                     # 封顶 70
        old = sj.score_subject([rec(published="2025-11-23")], AS_OF)
        self.assertAlmostEqual(old["records"][0]["decay"], 0.5, places=2)

    def test_category_filter(self):
        recs = [rec(), rec(code="92440101MA5B6QGE6M", dept="广州市越秀区烟草专卖局", wfxw="")]
        self.assertEqual(len(sj.rank(recs, AS_OF)), 2)
        food = sj.rank(recs, AS_OF, sj.CAT_FOOD)
        self.assertEqual([s["credit_code"] for s in food], ["91440104MAD3147042"])

    def test_profile(self):
        recs = [rec(id=1, fine=110000, result="罚款110,000元"), rec(id=2, published="2025-03-01"),
                rec(id=3, code="92440101MA5B6QGE6M", result="责令改正；警告", fine=None, wfxw="注册登记违法行为")]
        p = sj.profile(recs, AS_OF)
        self.assertEqual((p["record_count"], p["subject_count"], p["fined_count"], p["fine_total"]),
                         (3, 2, 2, 115000))
        self.assertEqual(p["by_category"][sj.CAT_FOOD]["records"], 2)
        self.assertEqual(p["by_category"][sj.CAT_LICENSE]["tiers"], {sr.TIER_ORDER: 1})
        self.assertEqual(p["by_year"], {"2025": {"records": 1, "fine_total": 5000.0},
                                        "2026": {"records": 2, "fine_total": 110000.0}})
        self.assertEqual([x["id"] for x in p["top_fines"]], [1, 2])
        self.assertEqual([x["record_count"] for x in p["repeat_subjects"]], [2])


class TestSubjectService(unittest.TestCase):
    """隔离库：用越秀真实详情样本（金石 648 号）+ 一份大写金额的合成详情走一遍采集，再查服务层和接口。"""

    @classmethod
    def setUpClass(cls):
        test_api.ApiTest.setUpClass()
        cls.api = test_api.ApiTest
        conn = connect()
        try:
            migrate(conn)
            conn.execute("DELETE FROM official_record WHERE source_id = %s", (yx.SOURCE_ID,))
            conn.commit()
            cls.root = tempfile.mkdtemp(prefix="snap_subj_")
            site = FakeSite()
            site.details[HONGTAI] = fake_detail(
                HONGTAI, cfXdrMc="广州宏泰餐饮有限公司", cfWsh="穗越市监处罚〔2026〕646号", cfJdrq="2026-11-16",
                cfXdrShxym="91440101MA9W0P22X3", cfCflb="罚款",
                cfNr="经查……决定给予如下行政处罚：罚款人民币壹拾肆万零伍佰元整(￥140500)。")
            yx.collect(conn, fetch=site, sleep=lambda s: None, snapshot_root=cls.root, guids=[JINSHI, HONGTAI])
        finally:
            conn.close()

    @classmethod
    def tearDownClass(cls):
        test_api.ApiTest.tearDownClass()

    def test_ranking_and_detail(self):
        conn = connect()
        try:
            r = svc.ranking(conn, as_of=AS_OF, snapshot_root=self.root)
            d = svc.subject_detail(conn, "91440101MA9W0P22X3", as_of=AS_OF, snapshot_root=self.root)
        finally:
            conn.close()
        self.assertEqual(r["total"], 2)
        self.assertEqual(r["subjects"][0]["subject"], "广州宏泰餐饮有限公司")             # 14 万排第一
        self.assertEqual(d["records"][0]["fine_amount"], 140500)
        self.assertEqual(d["records"][0]["category"], sj.CAT_FOOD)
        self.assertTrue(d["records"][0]["official_url"].startswith(yx.API))

    def test_api(self):
        code, data = self.api.call("GET", f"/api/v1/subjects/risk?as_of={AS_OF}", user="pr")
        self.assertEqual((code, data["total"], data["source_id"]), (200, 2, "yx_sgs"))
        key = data["subjects"][0]["subject_key"]
        code, d = self.api.call("GET", f"/api/v1/subjects/{key}/risk?as_of={AS_OF}", user="pr")
        self.assertEqual((code, d["subject_key"]), (200, key))
        code, p = self.api.call("GET", f"/api/v1/subjects/profile?as_of={AS_OF}", user="pr")
        self.assertEqual((code, p["record_count"], p["subject_count"]), (200, 2, 2))
        conn = connect()
        try:
            latest = conn.execute("SELECT MAX(published_at) FROM official_record WHERE source_id = %s",
                                  (yx.SOURCE_ID,)).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual((p["data_until"], p["as_of"]), (latest, AS_OF))     # 数据截止日和评估日期分开给
        self.assertEqual(self.api.call("GET", "/api/v1/subjects/NOPE/risk", user="pr")[0], 404)
        self.assertEqual(self.api.call("GET", "/api/v1/subjects/risk?source_id=gz_scjg", user="pr")[0], 400)
        self.assertEqual(self.api.call("GET", "/api/v1/subjects/risk?category=%E4%B9%B1%E5%86%99", user="pr")[0], 400)
        self.assertEqual(self.api.call("GET", "/api/v1/subjects/risk?as_of=2026-11", user="pr")[0], 400)

    def test_health_report(self):
        """第④步：体检报告和排名同口径，Markdown / PDF 都能导出，不存在的主体 404。"""
        code, rep = self.api.call("GET", f"/api/v1/subjects/91440101MA9W0P22X3/report?as_of={AS_OF}", user="pr")
        self.assertEqual((code, rep["level"]), (200, "中"))
        self.assertEqual([s["title"][:2] for s in rep["sections"]][:5], ["一、", "二、", "三、", "四、", "五、"])
        self.assertIn("2 个餐饮主体中排第 **1** 名", rep["sections"][0]["body"])
        self.assertIn("140,500 元", rep["sections"][0]["body"])
        code, md = self.api.call("GET", f"/api/v1/subjects/91440101MA9W0P22X3/report/export?as_of={AS_OF}",
                                 user="pr", raw=True)
        self.assertEqual(code, 200)
        md = md.decode("utf-8")
        self.assertTrue(md.startswith("# 广州宏泰餐饮有限公司 合规体检报告"))
        self.assertIn("穗越市监处罚〔2026〕646号", md)
        self.assertIn(yx.API, md)                                           # 每条都带原文链接
        code, pdf = self.api.call("GET", f"/api/v1/subjects/91440101MA9W0P22X3/report/export?format=pdf"
                                         f"&as_of={AS_OF}", user="pr", raw=True)
        self.assertEqual((code, pdf[:4]), (200, b"%PDF"))
        self.assertEqual(self.api.call("GET", "/api/v1/subjects/NOPE/report", user="pr")[0], 404)
        self.assertEqual(self.api.call("GET", "/api/v1/subjects/NOPE/report/export?format=doc", user="pr")[0], 422)


class TestSubjectReport(unittest.TestCase):
    def _report(self, recs, chain=None):
        from app.engine import subject_report as rp
        d = sj.score_subject(recs, AS_OF)
        return rp, rp.build(d, recs, {"as_of": AS_OF, "total": 5, "rank": 1, "category_total": 3,
                                      "category_rank": None}, chain)

    def test_sections_and_score_match_engine(self):
        recs = [rec(id=1, doc_no="A1", violation="《食品安全法》《食品安全法》未取得许可经营", fine=60000,
                    result="罚款60,000元"),
                rec(id=2, doc_no="B2", dept="广州市越秀区消防救援大队", wfxw="其他", fine=30000,
                    result="罚款30,000元；责令停产停业", published="2025-11-23")]
        rp, r = self._report(recs)
        self.assertEqual(r["score"], sj.score_subject(recs, AS_OF)["score"])
        body = "\n".join(s["body"] for s in r["sections"])
        self.assertIn("90,000 元", body)
        self.assertNotIn("¥", rp.to_markdown(r))                           # 黑体缺 ¥ 字形
        self.assertIn("《食品安全法》未取得", body)                          # 连写的法名去重
        self.assertIn("消防安全", body)
        self.assertIn("停业", body)
        self.assertNotIn("附：连锁", body)
        self.assertNotIn("只看食品安全", r["sections"][0]["body"])           # 不在食品榜就不写

    def test_chain_listed_without_scoring(self):
        recs = [rec(id=1, doc_no="A1")]
        chain = [rec(code="91440000X", subject="百胜餐饮(广东)有限公司广州肯德基某餐厅", doc_no="K1",
                     dept="广州市越秀区人民政府农林街道办事处", wfxw="住房和城乡建设",
                     regulation_text="《中华人民共和国消防法》第五十八条第三款")]
        _, r = self._report(recs, chain)
        sec = r["sections"][-2]
        self.assertEqual(sec["title"], "附：连锁品牌示例")
        self.assertIn("肯德基某餐厅", sec["body"])
        self.assertIn("消防安全", sec["body"])                               # 街道办执行消防法，不归市容
        self.assertIn("独立登记", sec["body"])                               # 各门店信用代码不同，不是同一张执照
        self.assertNotIn("同一张营业执照", sec["body"])

    def test_street_office_fire_law_is_fire(self):
        r = rec(dept="广州市越秀区人民政府珠光街道办事处", wfxw="行政违法行为",
                regulation_text="《中华人民共和国消防法》第五十八条")
        self.assertEqual(sj.classify(r), sj.CAT_FIRE)
        self.assertEqual(sj.classify(rec(dept="广州市越秀区人民政府珠光街道办事处", wfxw="行政违法行为")), sj.CAT_CITY)


if __name__ == "__main__":
    unittest.main()
