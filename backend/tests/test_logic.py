"""业务规则测试：评级、去重、预警静默、演示时钟、报告导出。"""
import unittest

import tests  # Initialize the isolated database even when discovery omits -t .

from app.engine import demo, reporting
from app.core.config import DEFAULT_CONFIG, LAST_BATCH, batch_label
from app.db.session import connect, get_config, one, rows
from app.engine.dedup import hamming, simhash
from app.engine.rating import level_of
from app.engine.tagging import tag


def event_levels(conn):
    return {e["id"]: (e["level"], e["intensity_score"]) for e in rows(conn, "SELECT * FROM event")}


class TestPureRules(unittest.TestCase):
    def test_level_thresholds(self):
        cfg = DEFAULT_CONFIG
        self.assertEqual(level_of(85, cfg), "S")
        self.assertEqual(level_of(84, cfg), "A")
        self.assertEqual(level_of(70, cfg), "A")
        self.assertEqual(level_of(69, cfg), "B")
        self.assertEqual(level_of(50, cfg), "B")
        self.assertEqual(level_of(49, cfg), "C")

    def test_batch_labels_numbered_0_to_7(self):
        self.assertEqual(LAST_BATCH, 7)
        self.assertEqual([batch_label(i) for i in range(8)],
                         ["T0", "T1", "T2", "T2.5", "T3", "T4", "T5", "T6"])

    def test_simhash_near_duplicate(self):
        a = simhash("香满园幸福路店后厨太脏了，大家千万别去吃，已经拉肚子了")
        b = simhash("香满园幸福路店后厨太脏了，大家千万别去吃，已经拉肚子了！！")
        c = simhash("香满园新品香辣鸡腿堡真好吃，推荐给大家")
        self.assertLessEqual(hamming(a, b), 3)
        self.assertGreater(hamming(a, c), 3)

    def test_tagging(self):
        t = tag({"text": "香满园后厨有老鼠，太恶心了，我要退款"})
        self.assertEqual(t["sentiment"], "负向")
        self.assertEqual(t["emotion"], "愤怒")
        self.assertIn("退款", t["sensitive_hits"])
        self.assertEqual(tag({"text": "香满园新品很好吃，推荐"})["sentiment"], "正向")


class TestDemoFlow(unittest.TestCase):
    """完整走一遍 T0→T6，核对设计方案里的演示剧本。"""

    @classmethod
    def setUpClass(cls):
        cls.per_batch = []
        r = demo.reset()
        cls.reset_result = r
        conn = connect()
        try:
            cls.per_batch.append(event_levels(conn))
            cls.advance_results = []
            for _ in range(LAST_BATCH):
                cls.advance_results.append(demo.advance(1))
                cls.per_batch.append(event_levels(conn))
            cls.alerts = rows(conn, "SELECT * FROM alert ORDER BY id")
            cls.n_main = conn.execute("SELECT COUNT(*) FROM content WHERE dup_of IS NULL").fetchone()[0]
            cls.n_dup = conn.execute("SELECT COUNT(*) FROM content WHERE dup_of IS NOT NULL").fetchone()[0]
            cls.filtered = get_config(conn)["filtered_total"]
            cls.clusters = rows(conn, "SELECT * FROM opinion_cluster WHERE event_id = 'ev001'")
        finally:
            conn.close()

    def test_level_progression(self):
        lv = [b["ev001"][0] for b in self.per_batch]
        # T0 C → T1 B → T2 A → T2.5 A → T3 S，之后保持 S
        self.assertEqual(lv[:5], ["C", "B", "A", "A", "S"])
        self.assertTrue(all(x == "S" for x in lv[4:]))
        self.assertEqual(self.per_batch[-1]["ev002"][0], "C")

    def test_alert_sequence_and_silence(self):
        seq = [(a["alert_type"], a["triggered_at"][11:], a["suppressed"]) for a in self.alerts]
        self.assertEqual(seq, [
            ("激增", "14:00", 0),   # T2 首次告警，静默到 15:00
            ("激增", "14:30", 1),   # T2.5 在静默期内，只留记录
            ("升级", "15:00", 0),   # T3 升到 S，升级告警不受静默限制
            ("激增", "16:00", 1),   # T4 恰好等于静默截止时刻（含端点）→ 仍抑制
        ])
        self.assertEqual(self.alerts[0]["notified"], ["站内通知"])
        self.assertEqual(self.alerts[1]["notified"], [])

    def test_kol_rule_in_upgrade_alert(self):
        up = self.alerts[2]
        self.assertIn("消费观察君（权重 10）", up["rule_desc"])
        self.assertIn("退款", up["rule_desc"])

    def test_dedup_and_filter_counts(self):
        self.assertEqual(self.n_dup, 2)                       # c112、c113 并入 c111
        self.assertEqual(self.filtered, 3)                    # c002、c216、c704
        self.assertGreater(self.n_main, 60)

    def test_clusters(self):
        negs = [c for c in self.clusters if c["sentiment"] == "负向"]
        self.assertGreaterEqual(len(negs), 3)
        for c in self.clusters:
            self.assertTrue(c["representative_content_ids"])

    def test_advance_past_end_is_noop(self):
        r = demo.advance(1)
        self.assertEqual(r["results"], [])
        self.assertTrue(r["finished"])

    def test_report_markdown_and_pdf(self):
        conn = connect()
        try:
            rep = reporting.build_report(conn, "ev001", get_config(conn))
            self.assertEqual(rep["gen_mode"], "模板生成")
            self.assertEqual(len(rep["sections"]), 5)
            row = {**rep, "id": 0, "event_id": "ev001", "created_by": "测试", "created_at": "2026-11-18 18:00:00"}
            md = reporting.to_markdown(row)
            self.assertIn("[c", md)                            # 带原文引用
            series = reporting._volume_series(rows(conn, "SELECT batch_no, sentiment FROM content "
                                                         "WHERE event_id = 'ev001' AND dup_of IS NULL"))
            try:
                pdf = reporting.to_pdf(row, series)
            except RuntimeError as e:
                self.skipTest(f"本机无中文字体：{e}")
            self.assertTrue(pdf.startswith(b"%PDF"))
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
