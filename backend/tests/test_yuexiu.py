"""越秀区双公示（企业全名行政处罚决定）采集器。

fixtures/yuexiu/ 下是 2026-11-23 真实请求一次列表、一次详情存下的原始 JSON，测试不联网。
"""
import json
import tempfile
import unittest
from pathlib import Path

import tests  # noqa: F401  先初始化隔离测试库

from app.collectors import http, pipeline, yuexiu_sgs as yx
from app.db.session import connect, migrate, one, rows
from app.engine import store_risk

FIX = Path(__file__).resolve().parent / "fixtures" / "yuexiu"
JINSHI = "3a1ad10e-e531-11f1-801f-2f75d2dc24ea"      # 广州市金石餐饮管理有限公司 穗越市监处罚〔2026〕648号
HONGTAI = "ba7d970e-e2d5-11f1-89dd-375a88756913"     # 广州宏泰餐饮有限公司（列表里的第二家餐饮）


def list_page() -> bytes:
    return (FIX / "list_p1.json").read_bytes()


def detail_jinshi() -> bytes:
    return (FIX / "detail_sample.json").read_bytes()


def fake_detail(guid: str, **override) -> bytes:
    d = json.loads(detail_jinshi())
    d["data"]["info"].update({"sGuid": guid, **override})
    return json.dumps(d, ensure_ascii=False).encode("utf-8")


class TestParse(unittest.TestCase):
    def test_list_page(self):
        items, total = yx.parse_list(list_page())
        self.assertEqual(total, 4584)
        self.assertEqual(len(items), 20)
        self.assertEqual(items[0]["subject"], "广州市越秀区汉耿烟酒商行")
        self.assertEqual(items[0]["doc_no"], "穗越市监处罚〔2026〕654号")
        self.assertEqual(items[0]["decided_at"], "2026-11-20")
        # 按名称筛餐饮：只有两家餐饮公司；烟酒行、干货、宾馆、花店都不算
        self.assertEqual([i["subject"] for i in items if yx.name_is_catering(i["subject"])],
                         ["广州市金石餐饮管理有限公司", "广州宏泰餐饮有限公司"])

    def test_detail_record_uses_decision_not_cfNrFk(self):
        info = yx.parse_detail(detail_jinshi())
        self.assertEqual(info["cfNrFk"], 1.0)               # 接口的罚款字段是错的
        r = yx.build_record(info, "sha", "2026-11-23 23:00:00")
        self.assertEqual(r["subject"], "广州市金石餐饮管理有限公司")
        self.assertEqual(r["doc_no"], "穗越市监处罚〔2026〕648号")
        self.assertIn("91440101MA59Q50MX9", r["article_title"])
        self.assertEqual(r["fine_amount"], 5000)
        self.assertEqual(r["handling_result"], "责令改正；警告；罚款5,000元；没收违法所得360元")
        self.assertNotIn("拟", r["handling_result"])
        self.assertEqual((r["published_at"], r["decided_at"]), ("2026-11-19", "2026-11-19"))
        self.assertEqual(r["enforcement_dept"], "广州市越秀区市场监督管理局")
        self.assertEqual(r["is_catering"], 1)
        self.assertIn("《中华人民共和国食品安全法》第一百二十五条第一款第(二)项", r["legal_basis"])
        self.assertEqual(r["source_category"], "官方通报")
        self.assertEqual(r["official_url"], yx.detail_url(JINSHI))
        g = store_risk.grade_record(r)
        self.assertEqual(g["tier"], store_risk.TIER_FINE)
        self.assertEqual(g["base"], 30 + store_risk.fine_bonus(5000))

    def test_proposed_amount_in_notice_is_ignored(self):
        content = ("本局向当事人送达《行政处罚告知书》，告知拟作出罚款10000元的行政处罚。当事人提出陈述申辩，"
                   "本局予以采纳。综上，本局作出如下处罚：1.警告；2.罚款3000元。")
        result, fine = yx.handling_result("警告;罚款", content)
        self.assertEqual(fine, 3000)
        self.assertEqual(result, "警告；罚款3,000元")

    def test_two_fines_are_summed_and_suspension_kept(self):
        content = "决定作出如下处罚：1.罚款20000元；2.罚款5000元；3.吊销食品经营许可证。"
        result, fine = yx.handling_result("罚款;吊销许可证件", content)
        self.assertEqual(fine, 25000)
        self.assertEqual(result, "罚款25,000元（20,000+5,000）；吊销许可证件")
        self.assertGreaterEqual(store_risk.grade_record({"handling_result": result, "fine_amount": fine})["base"],
                                30 + store_risk.SUSPEND_BONUS)

    def test_confiscation_amount_sum_is_not_fine(self):
        # 泰伴 491 号原文：「罚没款金额合计」= 没收 + 罚款，罚款只有 20000
        content = "我局决定责令当事人改正，并对当事人作出如下处罚:1.没收违法所得7024元;2.罚款20000元。罚没款金额合计27024元。"
        result, fine = yx.handling_result("罚款;没收违法所得、没收非法财物", content)
        self.assertEqual(fine, 20000)
        self.assertEqual(result, "责令改正；罚款20,000元；没收违法所得7,024元")

    def test_quoted_law_confiscation_is_not_goods(self):
        # 玥盈 28 号：没有决定引导语，法条引文里的「没收用于违法生产经营的工具」不算本案没收
        content = ("依据《广东省食品安全条例》第五十八条“……没收违法所得和违法生产经营的食品，并可以没收用于违法生产经营的"
                   "工具、设备、原料等物品……”的规定，决定责令当事人改正，没收违法所得1516.02元，并处罚款5000元，罚没款合计6516.02元。")
        result, fine = yx.handling_result("罚款;没收违法所得、没收非法财物", content)
        self.assertEqual(fine, 5000)
        self.assertEqual(result, "责令改正；罚款5,000元；没收违法所得1,516.02元")

    def test_goods_starting_with_quantity_are_confiscation(self):
        # 美妙 628 号：「没收8袋……」实物没收要列出
        content = "作出如下处罚:1.警告;2.没收8袋“AYOOLAPlantainFlour”(规格:0.9kg)标签未使用规范汉字的预包装食品;3.没收违法所得10元;4.罚款8000元。"
        result, fine = yx.handling_result("警告;罚款;没收违法所得、没收非法财物", content)
        self.assertEqual(fine, 8000)
        self.assertEqual(result, "警告；罚款8,000元；没收违法所得10元、没收非法财物")

    def test_quoted_goods_name_is_still_confiscation(self):
        # Codex v5 复核的合成反例：物品名用中文双引号，不是法条引文，实物没收要保留
        content = "本局决定没收违法所得10元；没收“装饰金箔”；罚款4000元。"
        result, fine = yx.handling_result("罚款;没收违法所得、没收非法财物", content)
        self.assertEqual(fine, 4000)
        self.assertEqual(result, "罚款4,000元；没收违法所得10元、没收非法财物")

    def test_quoted_goods_with_punctuation_is_still_confiscation(self):
        # Codex v6 复核的合成反例：物品名带规格、里面有逗号冒号，紧跟「没收」就是物品名
        content = "本局决定没收违法所得10元；没收“装饰金箔（规格：2g，数量：1瓶）”；罚款4000元。"
        result, fine = yx.handling_result("罚款;没收违法所得、没收非法财物", content)
        self.assertEqual(fine, 4000)
        self.assertEqual(result, "罚款4,000元；没收违法所得10元、没收非法财物")

    def test_short_law_quote_is_not_confiscation(self):
        # Codex v6 复核的合成反例：法条出处后面的短引文，再短也是法条，不算本案没收
        content = ("依据《中华人民共和国食品安全法》第一百二十四条“没收违法生产经营的食品”的规定，"
                   "决定责令当事人改正违法行为，没收违法所得10元，并处罚款4000元。")
        result, fine = yx.handling_result("罚款;没收违法所得、没收非法财物", content)
        self.assertEqual(fine, 4000)
        self.assertNotIn("非法财物", result)
        self.assertIn("没收违法所得10元", result)

    def test_fine_label_keeps_cents(self):
        # 溜六六 330 号：46,667.19 元不能写成 46,667 元；分项也保留角分（娟娟 183 号 36.x + 117.x）
        result, fine = yx.handling_result("罚款", "作出如下处罚:罚款46667.19元。")
        self.assertEqual((fine, result), (46667.19, "罚款46,667.19元"))
        result, fine = yx.handling_result("罚款", "作出如下处罚:1.罚款36.12元;2.罚款117.60元。")
        self.assertAlmostEqual(fine, 153.72)
        self.assertEqual(result, "罚款153.72元（36.12+117.60）")

    def test_catering_by_violation_type(self):
        info = yx.parse_detail(fake_detail("g1", cfXdrMc="广州市某某贸易有限公司", cfWfxw="餐饮服务经营者违法行为"))
        self.assertTrue(yx.is_catering(info))
        info = yx.parse_detail(fake_detail("g2", cfXdrMc="广州市某某贸易有限公司", cfWfxw="其他的食品销售违法行为"))
        self.assertFalse(yx.is_catering(info))


class FakeSite:
    def __init__(self, broken=()):
        self.calls, self.broken = [], set(broken)
        self.details = {JINSHI: detail_jinshi(),
                        HONGTAI: fake_detail(HONGTAI, cfXdrMc="广州宏泰餐饮有限公司", cfWsh="穗越市监处罚〔2026〕646号",
                                             cfJdrq="2026-11-16", cfXdrShxym="")}

    def __call__(self, url):
        self.calls.append(url)
        if "/list?" in url:
            body = list_page() if "pageNum=1&" in url else json.dumps({"datas": [], "page": {"total": 4584}}).encode()
            return http.Response(url, 200, body, 1)
        guid = url.split("sGuid=")[1]
        if guid in self.broken:
            raise http.FetchError(url, "HTTP 503", 503, 3)
        return http.Response(url, 200, self.details[guid], 1)


class TestCollect(unittest.TestCase):
    def setUp(self):
        self.conn = connect()
        migrate(self.conn)
        self.conn.execute("DELETE FROM official_record WHERE source_id = %s", (yx.SOURCE_ID,))
        self.conn.execute("DELETE FROM source_snapshot WHERE source_id = %s", (yx.SOURCE_ID,))
        self.conn.commit()
        self.root = tempfile.mkdtemp(prefix="snap_yx_")
        self.slept = []

    def tearDown(self):
        self.conn.close()

    def run_collect(self, site, **kw):
        return yx.collect(self.conn, fetch=site, sleep=self.slept.append, snapshot_root=self.root, **kw)

    def test_collect_catering_only_polite_and_idempotent(self):
        site = FakeSite()
        s = self.run_collect(site, max_pages=2)
        # 第 1 页 20 条，第 2 页空就停（翻页计 2 页）；只对 2 家餐饮取详情：共 2 页列表 + 2 详情 = 4 个请求
        self.assertEqual((s["pages"], s["listed"], s["candidates"], s["details"]), (2, 20, 2, 2))
        self.assertEqual(s["requests"], 4)
        self.assertEqual(self.slept, [yx.DEFAULT_DELAY] * 3)          # 每两个请求之间都等
        self.assertEqual((s["inserted"], s["catering"], s["errors"]), (2, 2, []))
        recs = rows(self.conn, "SELECT subject, doc_no, fine_amount, snapshot_sha256 FROM official_record "
                               "WHERE source_id = %s ORDER BY doc_no", (yx.SOURCE_ID,))
        self.assertEqual([r["subject"] for r in recs], ["广州宏泰餐饮有限公司", "广州市金石餐饮管理有限公司"])
        self.assertTrue(all(r["snapshot_sha256"] for r in recs))
        again = self.run_collect(FakeSite(), max_pages=1)
        self.assertEqual((again["inserted"], again["unchanged"]), (0, 2))

    def test_since_and_max_details(self):
        s = self.run_collect(FakeSite(), max_pages=3, since="2026-11-17")
        # 宏泰是 11-16，翻到它之前就停了
        self.assertEqual((s["listed"], s["candidates"], s["inserted"]), (10, 1, 1))
        site = FakeSite()
        s = self.run_collect(site, max_pages=1, max_details=1)
        self.assertEqual((s["candidates"], s["requests"]), (1, 2))

    def test_stops_at_total_even_if_api_repeats_last_page(self):
        # 真实接口翻过末页会重复返回最后一页（全量采时 total 4584、listed 4920）
        class RepeatingSite(FakeSite):
            def __call__(self, url):
                if "/list?" in url:
                    self.calls.append(url)
                    d = json.loads(list_page())
                    d["page"]["total"] = 25
                    return http.Response(url, 200, json.dumps(d).encode(), 1)
                return super().__call__(url)
        site = RepeatingSite()
        s = self.run_collect(site, max_pages=5)
        self.assertEqual(s["pages"], 2)                       # 2 页 × 20 ≥ 25 就停，不翻到第 5 页
        self.assertEqual(sum("/list?" in u for u in site.calls), 2)

    def test_aborts_after_consecutive_detail_errors(self):
        site = FakeSite(broken={JINSHI, HONGTAI})
        s = self.run_collect(site, guids=[JINSHI, HONGTAI, JINSHI, HONGTAI, JINSHI])
        self.assertEqual(len(s["errors"]), yx.MAX_CONSECUTIVE_ERRORS)
        self.assertIn("aborted", s)

    def test_detail_error_is_recorded_not_fatal(self):
        s = self.run_collect(FakeSite(broken={JINSHI}), max_pages=1)
        self.assertEqual((s["details"], s["inserted"], len(s["errors"])), (1, 1, 1))
        self.assertIn(JINSHI, s["errors"][0]["url"])

    def test_revision_and_reparse_from_snapshot(self):
        self.run_collect(FakeSite(), guids=[JINSHI])
        changed = FakeSite()
        changed.details[JINSHI] = fake_detail(JINSHI, cfNr="本局作出如下处罚：1.警告；2.罚款8000元。")
        s = self.run_collect(changed, guids=[JINSHI])
        self.assertEqual(s["revised"], 1)
        r = one(self.conn, "SELECT fine_amount, revision FROM official_record WHERE record_key = %s",
                (yx.record_key(JINSHI),))
        self.assertEqual((r["fine_amount"], r["revision"]), (8000, 2))
        # 不联网按快照重新解析：引用的是最新那份，金额不回退
        st = pipeline.reparse_snapshots(self.conn, yx.SOURCE_ID, snapshot_root=self.root)
        self.assertEqual(st["missing"], 0)
        r = one(self.conn, "SELECT fine_amount, revision FROM official_record WHERE record_key = %s",
                (yx.record_key(JINSHI),))
        self.assertEqual((r["fine_amount"], r["revision"]), (8000, 2))

    def test_links_to_store_by_license_subject(self):
        self.run_collect(FakeSite(), guids=[JINSHI])
        # 品牌关键词故意不含「金石」：只靠营业执照主体全名对上门店
        tid = self.conn.execute("INSERT INTO topic(name, keywords, channels) VALUES(%s, %s, %s)",
                                ("越秀测试品牌", json.dumps(["越秀测试品牌"]), "{}")).lastrowid
        sid = self.conn.execute("INSERT INTO store(topic_id, name, license_subject) VALUES(%s, %s, %s)",
                                (tid, "越秀测试品牌·东风店", "广州市金石餐饮管理有限公司")).lastrowid
        try:
            pipeline.link_records(self.conn)
            r = one(self.conn, "SELECT topic_id, store_id FROM official_record WHERE record_key = %s",
                    (yx.record_key(JINSHI),))
            self.assertEqual((r["topic_id"], r["store_id"]), (tid, sid))
        finally:
            self.conn.execute("UPDATE official_record SET topic_id = NULL, store_id = NULL WHERE topic_id = %s", (tid,))
            self.conn.execute("DELETE FROM store WHERE id = %s", (sid,))
            self.conn.execute("DELETE FROM topic WHERE id = %s", (tid,))
            self.conn.commit()


if __name__ == "__main__":
    unittest.main()
