"""第 ③ 步：门店风险评分。官方通报按处理结果分级、不算情绪分；投诉按每百店折算；风险落到门店；衰减按 published_at。"""
import json
import math
import unittest
from pathlib import Path

import tests  # noqa: F401  先初始化隔离测试库

from app.db.session import connect
from app.engine import demo
from app.engine import store_risk as sr
from app.services import store_risk_service
from tests import test_api

SEED = json.loads(Path(sr.__file__).with_name("official_seed.json").read_text(encoding="utf-8"))["records"]
AS_OF = "2026-11-23"


def rec(status="已处罚", result="责令改正；警告", fine=None, published="2026-11-23", **kw):
    return {"investigation_status": status, "handling_result": result, "fine_amount": fine,
            "published_at": published, **kw}


class TestGrading(unittest.TestCase):
    def test_tiers(self):
        self.assertEqual(sr.grade_record(rec("公安已立案", "移送公安机关；公安已立案侦查"))["tier"], sr.TIER_POLICE)
        self.assertEqual(sr.grade_record(rec(result="责令改正；罚款10,000元", fine=10000))["tier"], sr.TIER_FINE)
        self.assertEqual(sr.grade_record(rec(result="没收违法所得"))["tier"], sr.TIER_FINE)
        self.assertEqual(sr.grade_record(rec("已立案", "已立案调查"))["tier"], sr.TIER_CASE)
        self.assertEqual(sr.grade_record(rec())["tier"], sr.TIER_ORDER)

    def test_proposed_fine_is_not_a_penalty(self):
        g = sr.grade_record(rec(result="责令改正；警告；拟罚款5,000元（处罚告知阶段，非最终决定）"))
        self.assertEqual((g["tier"], g["base"]), (sr.TIER_ORDER, 10))
        self.assertIn("拟罚款", g["reason"])

    def test_fine_bonus_and_suspension(self):
        self.assertEqual(sr.fine_bonus(None), 0)
        self.assertEqual(sr.fine_bonus(500), 0)
        self.assertEqual(sr.fine_bonus(10000), 5.0)
        self.assertEqual(sr.fine_bonus(100000), 10.0)
        self.assertEqual(sr.fine_bonus(10 ** 8), 15)                        # 封顶
        g = sr.grade_record(rec(result="罚款100,000元；吊销食品经营许可证", fine=100000))
        self.assertEqual(g["base"], 30 + 10 + 10)
        # 金额只在罚没/移送公安档加分；拟罚款的 fine_amount 即使有值也不加
        self.assertEqual(sr.grade_record(rec(result="责令改正", fine=50000))["base"], 10)

    def test_no_sentiment_in_official_grade(self):
        a = sr.grade_record(rec(result="罚款10,000元", fine=10000, sentiment="负向", emotion="愤怒"))
        b = sr.grade_record(rec(result="罚款10,000元", fine=10000))
        self.assertEqual(a, b)

    def test_all_real_seed_records_grade(self):
        tiers = {}
        for r in SEED:
            tiers.setdefault(sr.grade_record(r)["tier"], []).append(r)
        self.assertEqual({k: len(v) for k, v in tiers.items()},
                         {sr.TIER_ORDER: 25, sr.TIER_FINE: 19, sr.TIER_POLICE: 10})
        # 两条拟罚款都落在警告/责令整改档
        self.assertTrue(all(sr.grade_record(r)["tier"] == sr.TIER_ORDER
                            for r in SEED if "拟罚款" in r["handling_result"]))
        tech = next(r for r in SEED if r["fine_amount"] == 75000)            # 技工学校 70,000+5,000
        self.assertEqual(sr.grade_record(tech)["base"], round(30 + 5 * math.log10(75), 1))


class TestDecay(unittest.TestCase):
    def test_uses_published_at_not_decided_at(self):
        a = sr.score_official(rec(published="2025-11-23", decided_at="2026-11-20"), AS_OF)
        self.assertAlmostEqual(a["decay"], 0.5, places=2)                    # 一年半衰
        no_decided = [r for r in SEED if not r["decided_at"]]
        self.assertTrue(no_decided)
        self.assertTrue(all(sr.score_official(r, AS_OF)["decay"] < 1 for r in no_decided))

    def test_edges(self):
        self.assertEqual(sr.decay(None, AS_OF, 365), 1.0)
        self.assertEqual(sr.decay("2027-01-01", AS_OF, 365), 1.0)            # 未来日期不加权
        self.assertEqual(sr.decay("2026-11", AS_OF, 365), sr.decay("2026-11-01", AS_OF, 365))
        self.assertAlmostEqual(sr.decay("2026-08-25", AS_OF, 90), 0.5, places=2)


class TestStoreScore(unittest.TestCase):
    STORE = {"id": 1, "name": "A·人民路店", "ownership": "加盟"}

    def test_complaints_count_only_customer_negative_non_dup(self):
        contents = [
            {"id": 1, "source_category": "顾客投诉", "sentiment": "负向", "published_at": AS_OF},
            {"id": 2, "source_category": "顾客投诉", "sentiment": "中性", "published_at": AS_OF},
            {"id": 3, "source_category": "顾客投诉", "sentiment": "正向", "published_at": AS_OF},
            {"id": 4, "source_category": "顾客投诉", "sentiment": "负向", "dup_of": "1", "published_at": AS_OF},
            {"id": 5, "source_category": "媒体报道", "sentiment": "负向", "published_at": AS_OF},
            {"id": 6, "source_category": "品牌回应", "sentiment": "中性", "published_at": AS_OF},
        ]
        s = sr.score_store(self.STORE, [], contents, AS_OF)
        self.assertEqual((s["complaint_count"], s["complaint_ids"], s["complaint_score"]), (2, [1, 2], 6.0))
        self.assertEqual((s["media_count"], s["brand_response_count"], s["official_count"]), (1, 1, 0))
        self.assertEqual((s["score"], s["level"]), (6, "低"))

    def test_caps_and_levels(self):
        police = [rec("公安已立案", "移送公安机关", id=i) for i in range(3)]
        many = [{"id": i, "source_category": "顾客投诉", "sentiment": "负向", "published_at": AS_OF}
                for i in range(20)]
        s = sr.score_store(self.STORE, police, many, AS_OF)
        self.assertEqual((s["official_score"], s["official_raw"]), (70, 150.0))
        self.assertEqual((s["complaint_score"], s["score"], s["level"], s["worst_tier"]), (30, 100, "高", "移送公安"))
        self.assertEqual(sr.score_store(self.STORE, [rec(result="罚款", fine=None)], [], AS_OF)["level"], "中")
        self.assertEqual(sr.score_store(self.STORE, [], [], AS_OF)["level"], "无")

    def test_officials_sorted_with_links(self):
        offs = [rec(id=1, official_url="u1"), rec("公安已立案", "移送公安机关", id=2, official_url="u2")]
        s = sr.score_store(self.STORE, offs, [], AS_OF)
        self.assertEqual([o["id"] for o in s["officials"]], [2, 1])
        self.assertTrue(all(o["official_url"] and o["reason"] for o in s["officials"]))


class TestBrandSummary(unittest.TestCase):
    def test_per_100_and_ownership(self):
        stores = [{"id": i, "name": f"S{i}", "ownership": "直营" if i < 3 else "加盟"} for i in range(4)]
        neg = {"source_category": "顾客投诉", "sentiment": "负向", "published_at": AS_OF}
        scores = [sr.score_store(stores[0], [], [neg] * 2, AS_OF), sr.score_store(stores[1], [], [], AS_OF),
                  sr.score_store(stores[2], [], [], AS_OF), sr.score_store(stores[3], [rec()], [neg] * 3, AS_OF)]
        unlinked = [rec(id=99, subject="品牌某店", official_url="u")]
        b = sr.brand_summary(stores, scores, unlinked, 1, AS_OF)
        self.assertEqual((b["complaints_total"], b["complaints_per_100_stores"]), (6, 150.0))
        self.assertEqual((b["officials_total"], b["officials_per_100_stores"]), (2, 50.0))
        self.assertEqual(b["by_ownership"]["直营"]["complaints_per_100_stores"], round(200 / 3, 1))
        self.assertEqual(b["by_ownership"]["加盟"]["complaints_per_100_stores"], 300.0)
        self.assertEqual(b["stores"][0]["store_id"], 3)                      # 按分数排
        self.assertEqual([u["id"] for u in b["unlinked_officials"]], [99])  # 分不清哪家店的不摊到门店
        self.assertEqual(sr.per_100(3, 0), None)


class TestStep3Service(unittest.TestCase):
    """在隔离库里挂一条真实官方记录到演示门店，检查服务层与接口。"""

    @classmethod
    def setUpClass(cls):
        demo.reset()
        demo.advance(10)
        test_api.ApiTest.setUpClass()
        cls.api = test_api.ApiTest
        conn = connect()
        try:
            st = conn.execute("SELECT id, topic_id FROM store ORDER BY id LIMIT 1").fetchone()
            cls.sid, cls.tid = st["id"], st["topic_id"]
            r = conn.execute("SELECT id FROM official_record WHERE fine_amount = 75000").fetchone()
            cls.rid = r["id"]
            conn.execute("UPDATE official_record SET topic_id = %s, store_id = %s WHERE id = %s",
                         (cls.tid, cls.sid, cls.rid))
            conn.commit()
        finally:
            conn.close()

    @classmethod
    def tearDownClass(cls):
        test_api.ApiTest.tearDownClass()

    def test_topic_risk(self):
        conn = connect()
        try:
            b = store_risk_service.topic_risk(conn, self.tid, AS_OF)
        finally:
            conn.close()
        self.assertEqual(b["store_count"], 4)
        top = next(s for s in b["stores"] if s["store_id"] == self.sid)
        self.assertEqual(top["official_count"], 1)
        self.assertEqual(top["officials"][0]["tier"], sr.TIER_FINE)
        self.assertGreater(b["complaints_total"], 0)
        self.assertEqual(b["complaints_per_100_stores"], round(b["complaints_total"] * 100 / 4, 1))

    def test_api(self):
        code, data = self.api.call("GET", f"/api/v1/stores/risk?topic_id={self.tid}&as_of={AS_OF}", user="pr")
        self.assertEqual((code, data["topic_id"], data["as_of"]), (200, self.tid, AS_OF))
        code, allb = self.api.call("GET", "/api/v1/stores/risk", user="pr")
        self.assertEqual(code, 200)
        self.assertIn(self.tid, [b["topic_id"] for b in allb])
        code, d = self.api.call("GET", f"/api/v1/stores/{self.sid}/risk?as_of={AS_OF}", user="pr")
        self.assertEqual((code, d["store_id"], d["officials"][0]["id"]), (200, self.sid, self.rid))
        self.assertEqual(self.api.call("GET", "/api/v1/stores/999999/risk", user="pr")[0], 404)
        self.assertEqual(self.api.call("GET", f"/api/v1/stores/risk?topic_id={self.tid}&as_of=2026-11",
                                       user="pr")[0], 400)
        self.assertEqual(self.api.call("GET", "/api/v1/stores/risk?topic_id=999999", user="pr")[0], 404)


if __name__ == "__main__":
    unittest.main()
