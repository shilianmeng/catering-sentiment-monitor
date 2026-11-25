"""第 ② 步：门店表、来源类别、真实官方处罚采集（重试 / 快照 / 去重 / 改稿识别）。

解析测试用的是 tests/fixtures/official/ 下真实抓下来的两篇官方公告原网页，不联网。
"""
import hashlib
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path

import tests  # noqa: F401  先初始化隔离测试库

from app.collectors import gkmlpt, http, pipeline, snapshot
from app.core import config
from app.db.session import connect, migrate, one, rows
from app.engine import demo, sources
from tests import test_api   # 只取它的起服务/调用工具；模块对象不会被 unittest 当成用例重复跑

FIX = Path(__file__).resolve().parent / "fixtures" / "official"
GZ_URL = "http://scjgj.gz.gov.cn/gkmlpt/content/10/10604/post_10604453.html"
SZ_URL = "https://amr.sz.gov.cn/gkmlpt/content/12/12897/post_12897525.html"
GZ, SZ = config.OFFICIAL_SOURCES


def gz_page():
    return (FIX / "gz_post_10604453.html").read_bytes()


def sz_page():
    return (FIX / "sz_post_12897525.html").read_bytes()


class TestParseRealPages(unittest.TestCase):
    """真实公告原网页 → 逐案记录。"""

    def test_guangzhou_eight_cases(self):
        a = gkmlpt.parse_article(gz_page(), GZ_URL, GZ)
        self.assertEqual(a["title"], "广州市市场监督管理局公布2025年食品安全全链条监管典型案例")
        self.assertEqual(a["published_at"], "2025-12-22")
        self.assertEqual(len(a["cases"]), 8)
        c = {x["case_no"]: x for x in a["cases"]}
        self.assertEqual(c[1]["subject"], "刘某某")
        self.assertEqual(c[1]["shops"], ["醉仙脆皮烧鸡（大岗店）"])          # 门店名从正文引号里取
        self.assertEqual(c[2]["subject"], "白云区某餐饮店")
        self.assertEqual(c[2]["enforcement_dept"], "白云区市场监管局")
        self.assertEqual(c[2]["decided_at"], "2025-08-20")
        self.assertEqual(c[2]["investigation_status"], "公安已立案")
        self.assertEqual(c[3]["fine_amount"], 100000)
        self.assertEqual(c[3]["investigation_status"], "已处罚")
        self.assertIn("《中华人民共和国食品安全法》第一百二十三条第一款", c[3]["legal_basis"])
        self.assertEqual(c[8]["handling_result"], "责令改正；罚款50,000元")
        # 餐饮主体：餐饮店、凉茶店、汤粉店、外卖；食品公司、供应链、微信卖糖果的不算
        self.assertEqual([n for n in c if c[n]["is_catering"]], [1, 2, 4, 5])
        self.assertTrue(all(not x["violation"].startswith("案情") for x in a["cases"]))

    def test_shenzhen_split_heading_and_police_status(self):
        a = gkmlpt.parse_article(sz_page(), SZ_URL, SZ)
        self.assertEqual(a["doc_no"], "深市监公告〔2026〕27号")
        self.assertEqual([x["subject"] for x in a["cases"]],
                         ["深圳市罗湖区老河间驴肉火烧店", "坪山区某私宰肉品违法团伙", "深圳市六禾供应链有限公司"])
        c1, c2, _ = a["cases"]
        self.assertEqual(c1["enforcement_dept"], "深圳市市场监督管理局罗湖监管局")
        # 只说「移送」、公安还在调查 ≠ 公安已立案
        self.assertEqual(c1["investigation_status"], "已移送公安")
        self.assertEqual(c2["investigation_status"], "公安已立案")
        self.assertTrue(c1["is_catering"])
        self.assertFalse(c2["is_catering"])
        # 公告末尾的「案件剖析及警示」和落款不能混进第三起案件
        self.assertNotIn("案件剖析", a["cases"][2]["violation"])

    def test_subject_from_dept_prefixed_titles(self):
        t = "海珠区市场监管局查处广州市某餐饮管理有限公司海珠宝岗店未主动对消费者进行防止食品浪费提示提醒案"
        self.assertEqual(gkmlpt.split_title(t)[0], "海珠区市场监管局")
        self.assertEqual(gkmlpt.subject_of(t), "广州市某餐饮管理有限公司海珠宝岗店")
        self.assertEqual(gkmlpt.subject_of("李某经营无证餐饮店案"), "李某")
        self.assertEqual(gkmlpt.subject_of("从化区市场监管局查处从化城郊某某私厨馆未主动对消费者进行提醒案"),
                         "从化城郊某某私厨馆")

    def test_status_and_result_wording(self):
        self.assertEqual(gkmlpt.investigation_status("该局对当事人作出责令立即整改，并给予警告。"), "已处罚")
        self.assertEqual(gkmlpt.handling_result("该局对当事人作出责令立即整改，并给予警告。"), "责令改正；警告")
        self.assertEqual(gkmlpt.investigation_status("将案件移交公安部门处理。"), "已移送公安")
        self.assertEqual(gkmlpt.fines("处罚款1.5万元，另罚款3,000元"), [15000.0, 3000.0])
        self.assertIn("罚款（公告未列金额）", gkmlpt.handling_result("对当事人处以罚款。"))

    def test_list_filter(self):
        body = json.dumps({"articles": [
            {"title": "广州市市场监督管理局公布2025年食品安全全链条监管典型案例", "url": GZ_URL, "date": 1766332800},
            {"title": "关于印发2026年餐饮环节食品安全监督检查计划的通知", "url": "http://x/2", "date": 1766332800},
        ]}).encode()
        listed = gkmlpt.parse_list(body)
        self.assertEqual(listed[0]["published_at"], "2025-12-22")              # 按北京时间算日期
        self.assertEqual([a["url"] for a in listed if gkmlpt.is_candidate(a["title"])], [GZ_URL])
        real = gkmlpt.parse_list((FIX / "gz_list_page1.json").read_bytes())   # 真实列表接口的返回
        self.assertGreater(len(real), 10)
        self.assertTrue(all(a["url"].startswith("http") for a in real))


class TestFetchRetry(unittest.TestCase):
    def test_retries_then_succeeds_with_backoff(self):
        replies, waits = [(503, b""), (502, b""), (200, b"ok")], []
        resp = http.fetch("u", opener=lambda url, t: replies.pop(0), sleep=waits.append, backoff=1)
        self.assertEqual((resp.body, resp.attempts), (b"ok", 3))
        self.assertEqual(waits, [1, 2])                                       # 指数退避

    def test_no_retry_on_404(self):
        calls = []

        def opener(url, t):
            calls.append(url)
            raise urllib.error.HTTPError(url, 404, "nf", {}, None)
        with self.assertRaises(http.FetchError) as ctx:
            http.fetch("u", opener=opener, sleep=lambda s: None)
        self.assertEqual((len(calls), ctx.exception.status), (1, 404))

    def test_network_error_exhausts_retries(self):
        def opener(url, t):
            raise urllib.error.URLError("timed out")
        with self.assertRaises(http.FetchError) as ctx:
            http.fetch("u", opener=opener, sleep=lambda s: None, retries=3)
        self.assertEqual(ctx.exception.attempts, 3)


class FakeSite:
    """假官网：列表一页 + 两篇真实公告网页，可以让某个 URL 故障或改稿。"""

    def __init__(self):
        self.pages = {GZ_URL: gz_page()}
        self.broken = set()
        self.listing = [{"title": "广州市市场监督管理局公布2025年食品安全全链条监管典型案例",
                         "url": GZ_URL, "date": 1766332800},
                        {"title": "广州市市场监督管理局公布校园食品安全案件查办典型案例",
                         "url": "http://scjgj.gz.gov.cn/broken.html", "date": 1713196800},
                        {"title": "广州市市场监督管理局召开工作会议", "url": "http://x/meeting", "date": 1}]

    def __call__(self, url):
        if "/gkmlpt/api/all/" in url:
            arts = self.listing if "page=1" in url else []
            return http.Response(url, 200, json.dumps({"articles": arts}).encode(), 1)
        if url in self.broken or url not in self.pages:
            raise http.FetchError(url, "HTTP 503", 503, 3)
        return http.Response(url, 200, self.pages[url], 1)


class TestPipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        demo.reset()

    def setUp(self):
        self.conn = connect()
        self.conn.execute("DELETE FROM official_record WHERE source_id = 'gz_amr' AND official_url = %s", (GZ_URL,))
        self.conn.commit()
        self.root = tempfile.mkdtemp(prefix="snap_")

    def tearDown(self):
        self.conn.close()

    def test_collect_dedup_revision_and_snapshot(self):
        site = FakeSite()
        s1 = pipeline.collect(self.conn, "gz_amr", max_pages=3, fetch=site, snapshot_root=self.root)
        self.assertEqual((s1["listed"], s1["candidates"], s1["articles"]), (3, 2, 1))
        self.assertEqual((s1["cases"], s1["inserted"]), (8, 8))
        self.assertEqual(len(s1["errors"]), 1)                       # 一篇抓不到只记错误，不影响其它
        recs = rows(self.conn, "SELECT * FROM official_record WHERE official_url = %s ORDER BY case_no", (GZ_URL,))
        self.assertEqual(len(recs), 8)
        self.assertTrue(all(r["source_category"] == "官方通报" and r["snapshot_sha256"] for r in recs))
        # 快照可回溯，且 hash 对得上
        self.assertEqual(snapshot.load(recs[0]["snapshot_sha256"], self.root), gz_page())

        s2 = pipeline.collect(self.conn, "gz_amr", max_pages=3, fetch=site, snapshot_root=self.root)
        self.assertEqual((s2["inserted"], s2["unchanged"]), (0, 8))  # 重复采集不重复入库

        site.pages[GZ_URL] = gz_page().replace("50000元".encode(), "60000元".encode())   # 官方改稿
        s3 = pipeline.collect(self.conn, "gz_amr", max_pages=3, fetch=site, snapshot_root=self.root)
        self.assertEqual((s3["revised"], s3["unchanged"]), (1, 7))
        r8 = one(self.conn, "SELECT fine_amount, revision FROM official_record WHERE official_url = %s AND case_no = 8",
                 (GZ_URL,))
        self.assertEqual((r8["fine_amount"], r8["revision"]), (60000, 2))

    def test_tampered_snapshot_rejected(self):
        sha = snapshot.save(self.conn, GZ_URL, "gz_amr", b"<html>x</html>", root=self.root)
        snapshot.path_for(sha, self.root).write_bytes(b"<html>changed</html>")
        self.assertIsNone(snapshot.load(sha, self.root))
        self.conn.rollback()

    def test_reparse_does_not_count_as_revision(self):
        site = FakeSite()
        pipeline.collect(self.conn, "gz_amr", fetch=site, snapshot_root=self.root)
        self.conn.execute("UPDATE official_record SET subject = '旧解析', content_hash = 'x' WHERE official_url = %s",
                          (GZ_URL,))
        self.conn.commit()
        st = pipeline.reparse_snapshots(self.conn, "gz_amr", snapshot_root=self.root)
        self.assertGreaterEqual(st["reparsed"], 8)
        r = one(self.conn, "SELECT subject, revision FROM official_record WHERE official_url = %s AND case_no = 1",
                (GZ_URL,))
        self.assertEqual((r["subject"], r["revision"]), ("刘某某", 1))


class TestOfficialSeed(unittest.TestCase):
    def test_seed_is_real_and_loaded_on_reset(self):
        seed = json.loads(config.OFFICIAL_SEED_FILE.read_text(encoding="utf-8"))["records"]
        self.assertGreaterEqual(len(seed), 40)
        hosts = {r["official_url"].split("/")[2] for r in seed}
        self.assertEqual(hosts, {"scjgj.gz.gov.cn", "amr.sz.gov.cn"})          # 两个真实官方源
        self.assertTrue(all(r["snapshot_sha256"] and len(r["snapshot_sha256"]) == 64 for r in seed))
        self.assertGreaterEqual(sum(r["is_catering"] for r in seed), 20)
        demo.reset()
        demo.reset()                                                           # 重置两次不重复
        conn = connect()
        try:
            n = conn.execute("SELECT COUNT(*) FROM official_record").fetchone()[0]
            self.assertGreaterEqual(n, len(seed))
            keys = {r["record_key"] for r in rows(conn, "SELECT record_key FROM official_record")}
            self.assertTrue({r["record_key"] for r in seed} <= keys)
        finally:
            conn.close()

    def test_guarded_reset_keeps_collected_records(self):
        """start.ps1 -Reset 走 guarded_reset：采集来的记录（不在种子里）先备份，重置后逐条不变。"""
        demo.reset()
        key = hashlib.sha256(b"guard-reset-test").hexdigest()
        conn = connect()
        try:
            pipeline.upsert_record(conn, {
                "record_key": key, "content_hash": key, "source_id": "yx_sgs", "source_name": "越秀区市场监管局",
                "source_category": "双公示", "official_url": "https://example.invalid/guard", "article_title": None,
                "doc_no": "穗越市监处罚〔2026〕999号", "case_no": 1, "case_title": "防误删测试", "subject": "测试主体",
                "enforcement_dept": None, "region": "越秀区", "published_at": "2026-11-01", "decided_at": "2026-10-30",
                "violation": "x", "legal_basis": [], "regulation_text": None, "investigation_status": "已处罚",
                "handling_result": "罚款1,234.56元", "fine_amount": 1234.56, "is_catering": 1,
                "snapshot_sha256": None, "parser_version": 7, "fetched_at": "2026-11-23"})
            conn.commit()
        finally:
            conn.close()
        with tempfile.TemporaryDirectory() as d:
            r = demo.guarded_reset(d)
            backup = json.loads(Path(r["backup"]).read_text(encoding="utf-8"))
            self.assertIn(key, {x["record_key"] for x in backup["records"]})
            self.assertEqual(backup["count"], r["official_before"])
        self.assertEqual((r["official_lost"], r["official_changed"]), ([], []))
        self.assertEqual(r["official_after"], r["official_before"])
        conn = connect()
        try:
            row = one(conn, "SELECT fine_amount, parser_version, handling_result FROM official_record "
                            "WHERE record_key = %s", (key,))
            self.assertEqual((row["fine_amount"], row["parser_version"], row["handling_result"]),
                             (1234.56, 7, "罚款1,234.56元"))
            conn.execute("DELETE FROM official_record WHERE record_key = %s", (key,))
            conn.commit()
        finally:
            conn.close()

    def test_link_record_to_brand_topic(self):
        demo.reset()
        conn = connect()
        try:
            cur = conn.execute("INSERT INTO topic(name, keywords, channels, brand, entities, event_rules, enabled) "
                               "VALUES('驴肉火烧监测', %s, '{}', '老河间', '[]', '[]', 1)",
                               (json.dumps(["老河间"], ensure_ascii=False),))
            tid = cur.lastrowid
            sid = conn.execute("INSERT INTO store(topic_id, name, aliases, ownership) VALUES(%s,%s,%s,'加盟')",
                               (tid, "老河间·罗湖店", json.dumps(["罗湖区老河间"], ensure_ascii=False))).lastrowid
            pipeline.link_records(conn)
            r = one(conn, "SELECT topic_id, store_id FROM official_record WHERE subject LIKE %s", ("%老河间%",))
            self.assertEqual((r["topic_id"], r["store_id"]), (tid, sid))
        finally:
            conn.rollback()
            conn.close()


class TestStoresAndCategories(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        demo.reset()
        demo.advance(10)

    def test_demo_stores_seeded_with_ownership(self):
        conn = connect()
        try:
            stores = {s["name"]: s for s in rows(conn, "SELECT * FROM store")}
        finally:
            conn.close()
        self.assertEqual(len(stores), 4)
        self.assertEqual({s["ownership"] for s in stores.values()}, {"直营", "加盟"})
        self.assertTrue(all(s["district"] for s in stores.values()))

    def test_content_has_category_and_store(self):
        conn = connect()
        try:
            cats = {r["source_category"] for r in rows(conn, "SELECT DISTINCT source_category FROM content")}
            self.assertEqual(cats, {"媒体报道", "顾客投诉", "品牌回应"})
            brand_stmt = one(conn, "SELECT source_category FROM content WHERE author_type = '官方' LIMIT 1")
            self.assertEqual(brand_stmt["source_category"], "品牌回应")   # 品牌自己的声明不算官方通报
            n = conn.execute("SELECT COUNT(*) FROM content c JOIN store s ON s.id = c.store_id "
                             "WHERE s.aliases LIKE %s", ("%幸福路店%",)).fetchone()[0]
            self.assertGreater(n, 10)
        finally:
            conn.close()

    def test_category_rules(self):
        self.assertEqual(sources.source_category({"author": "某区市场监督管理局"}), "官方通报")
        self.assertEqual(sources.source_category({"source_type": "新闻门户"}), "媒体报道")
        self.assertEqual(sources.source_category({"source_category": "官方通报", "author_type": "普通"}), "官方通报")
        stores = [{"name": "A·人民路店", "aliases": ["人民路店"]}, {"name": "A·人民路二店", "aliases": ["人民路二店"]}]
        self.assertEqual(sources.match_store(stores, "去了人民路二店")["name"], "A·人民路二店")

    def test_old_db_upgrade_backfills(self):
        conn = connect()
        try:
            conn.execute("ALTER TABLE content DROP COLUMN source_category")
            conn.execute("ALTER TABLE content DROP COLUMN store_id")
            # 早先手工建过的旧版 store：只有 type / region，没有 ownership / aliases
            tid = conn.execute("SELECT id FROM topic ORDER BY id LIMIT 1").fetchone()["id"]
            conn.execute("DROP TABLE store")
            conn.execute("CREATE TABLE store (id INT PRIMARY KEY AUTO_INCREMENT, topic_id INT, name LONGTEXT NOT NULL, "
                         "type VARCHAR(16) DEFAULT '未知', region LONGTEXT, address LONGTEXT, "
                         "status VARCHAR(16) NOT NULL DEFAULT '营业', created_at LONGTEXT)")
            conn.execute("INSERT INTO store(topic_id, name, type, region) VALUES(%s, %s, '加盟', '华东')",
                         (tid, "香满园·幸福路店"))
            conn.commit()
            migrate(conn)
        finally:
            conn.close()
        demo.ensure_db()
        conn = connect()
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM store").fetchone()[0], 4)   # 旧的 1 家 + 补 3 家
            old = one(conn, "SELECT ownership, province, aliases FROM store WHERE name = %s", ("香满园·幸福路店",))
            self.assertEqual((old["ownership"], old["province"], old["aliases"]), ("加盟", "华东", ["幸福路店"]))
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM content WHERE source_category IS NULL")
                             .fetchone()[0], 0)
            self.assertGreater(conn.execute("SELECT COUNT(*) FROM content WHERE store_id IS NOT NULL")
                               .fetchone()[0], 10)
        finally:
            conn.close()


class TestStep2Api(unittest.TestCase):
    """接口：门店增删改查与权限、官方记录检索与详情。复用 test_api 的起服务和登录。"""

    @classmethod
    def setUpClass(cls):
        test_api.ApiTest.setUpClass()
        cls.api = test_api.ApiTest

    @classmethod
    def tearDownClass(cls):
        test_api.ApiTest.tearDownClass()

    def test_official_records(self):
        code, data = self.api.call("GET", "/api/v1/official/records?catering=true&page_size=100", user="pr")
        self.assertEqual(code, 200)
        self.assertGreaterEqual(data["total"], 20)
        self.assertTrue(all(r["is_catering"] == 1 and r["official_url"].startswith("http") for r in data["items"]))
        code, rec = self.api.call("GET", f"/api/v1/official/records/{data['items'][0]['id']}", user="pr")
        self.assertEqual(code, 200)
        self.assertIsInstance(rec["legal_basis"], list)
        code, srcs = self.api.call("GET", "/api/v1/official/sources", user="analyst")
        self.assertEqual([s["id"] for s in srcs], ["gz_amr", "sz_amr"])
        self.assertTrue(all(s["records"] > 0 for s in srcs))
        code, _ = self.api.call("POST", "/api/v1/official/collect", {"source_id": "gz_amr"}, user="analyst")
        self.assertEqual(code, 403)                                    # 触发采集只给管理员
        code, _ = self.api.call("POST", "/api/v1/official/collect", {"source_id": "nope"}, user="admin")
        self.assertEqual(code, 400)

    def test_end_to_end_collect_to_store_api(self):
        """端到端：官网（假）→ 采集 → 快照 → 入库 → 挂到品牌门店 → 接口按门店查得到、详情能回溯快照。"""
        conn = connect()
        try:
            conn.execute("DELETE FROM official_record WHERE official_url = %s", (GZ_URL,))
            tid = conn.execute("INSERT INTO topic(name, keywords, channels, brand, entities, event_rules, enabled) "
                               "VALUES('汤粉王监测', %s, '{}', '汤粉王', '[]', '[]', 1)",
                               (json.dumps(["汤粉王"], ensure_ascii=False),)).lastrowid
            sid = conn.execute("INSERT INTO store(topic_id, name, aliases, ownership) VALUES(%s,%s,%s,'加盟')",
                               (tid, "汤粉王·增城店", json.dumps(["增城某汤粉王店"], ensure_ascii=False))).lastrowid
            conn.commit()
            stats = pipeline.collect(conn, "gz_amr", max_pages=1, fetch=FakeSite())
            self.assertEqual(stats["inserted"], 8)
            self.assertGreaterEqual(stats["linked"], 1)
        finally:
            conn.close()

        code, data = self.api.call("GET", f"/api/v1/official/records?store_id={sid}", user="pr")
        self.assertEqual((code, data["total"]), (200, 1))
        rec = data["items"][0]
        self.assertEqual((rec["subject"], rec["topic_id"], rec["investigation_status"]),
                         ("增城某汤粉王店", tid, "公安已立案"))
        self.assertEqual(rec["official_url"], GZ_URL)
        code, det = self.api.call("GET", f"/api/v1/official/records/{rec['id']}", user="pr")
        self.assertEqual(code, 200)
        self.assertTrue(det["snapshot"]["available"])                 # 原网页快照在、hash 对得上
        code, st = self.api.call("GET", f"/api/v1/stores/{sid}", user="pr")
        self.assertEqual((code, st["official_count"], st["ownership"]), (200, 1, "加盟"))

    def test_store_crud_and_permissions(self):
        code, stores = self.api.call("GET", "/api/v1/stores", user="pr")
        self.assertEqual(code, 200)
        tid = stores[0]["topic_id"]
        xf = next(s for s in stores if "幸福路店" in s["aliases"])
        self.assertGreater(xf["content_count"], 0)
        body = {"topic_id": tid, "name": "测试·新店", "aliases": ["新店"], "ownership": "加盟", "city": "演示市"}
        self.assertEqual(self.api.call("POST", "/api/v1/stores", body, user="pr")[0], 403)
        code, st = self.api.call("POST", "/api/v1/stores", body, user="analyst")
        self.assertEqual((code, st["ownership"]), (200, "加盟"))
        self.assertEqual(self.api.call("POST", "/api/v1/stores", body, user="analyst")[0], 409)
        bad = {**body, "name": "测试·怪店", "ownership": "合营"}
        self.assertEqual(self.api.call("POST", "/api/v1/stores", bad, user="analyst")[0], 400)
        code, st2 = self.api.call("PUT", f"/api/v1/stores/{st['id']}", {"status": "停业整改"}, user="admin")
        self.assertEqual((code, st2["status"], st2["ownership"]), (200, "停业整改", "加盟"))
        self.assertEqual(self.api.call("DELETE", f"/api/v1/stores/{st['id']}", user="admin")[0], 200)
        # 已有内容关联的门店不能删
        self.assertEqual(self.api.call("DELETE", f"/api/v1/stores/{xf['id']}", user="admin")[0], 409)

    def test_content_filter_by_category(self):
        code, data = self.api.call("GET", "/api/v1/contents?source_category=%E9%A1%BE%E5%AE%A2%E6%8A%95%E8%AF%89"  # 顾客投诉
                                          "&page_size=50", user="analyst")
        self.assertEqual(code, 200)
        self.assertGreater(data["total"], 0)
        self.assertTrue(all(c["source_category"] == "顾客投诉" for c in data["items"]))


if __name__ == "__main__":
    unittest.main()


REG_PAGE = """<html><body><p>发布日期：2024-05-01 浏览次数：1</p>
<p>一、广州市荔湾区市场监督管理局查处某幼儿园从事餐饮服务经营者违法行为案</p>
<p>案情：经查，当事人未按规定公示食品安全信息。荔湾区市场监管局依法对当事人作出责令改正、给予警告的行政处罚。
违反本法规定，有下列情形之一的，由县级以上人民政府食品安全监督管理部门没收违法所得，罚款5万元，情节严重的，责令停业，吊销许可证。</p>
<p>相关规定：</p>
<p>《中华人民共和国食品安全法》第一百二十二条：由县级以上人民政府食品安全监督管理部门没收违法所得；并处罚款10万元；情节严重的，责令停产停业，直至吊销许可证。</p>
</body></html>""".encode("utf-8")


class TestCodexReviewStep2(unittest.TestCase):
    """Codex 第②步审查的 6 个缺陷，各一条回归测试。"""

    @classmethod
    def setUpClass(cls):
        demo.reset()

    def setUp(self):
        self.conn = connect()
        self.conn.execute("DELETE FROM official_record WHERE official_url = %s", (GZ_URL,))
        self.conn.commit()
        self.root = tempfile.mkdtemp(prefix="snap_")

    def tearDown(self):
        self.conn.rollback()
        self.conn.execute("DELETE FROM official_record WHERE official_url = %s", (GZ_URL,))
        self.conn.commit()
        self.conn.close()

    def _r8(self):
        return one(self.conn, "SELECT fine_amount, revision FROM official_record WHERE official_url = %s AND case_no = 8",
                   (GZ_URL,))

    def _collect_then_revise(self):
        site = FakeSite()
        pipeline.collect(self.conn, "gz_amr", fetch=site, snapshot_root=self.root)
        seed = Path(self.root) / "old_seed.json"
        pipeline.export_seed(self.conn, seed)                      # 改稿前的种子
        site.pages[GZ_URL] = gz_page().replace("50000元".encode(), "60000元".encode())
        pipeline.collect(self.conn, "gz_amr", fetch=site, snapshot_root=self.root)
        self.assertEqual((self._r8()["fine_amount"], self._r8()["revision"]), (60000, 2))
        return seed

    def test_1_regulation_appendix_not_taken_as_decision(self):
        case = gkmlpt.parse_article(REG_PAGE, "http://x/reg", GZ)["cases"][0]
        self.assertEqual(case["handling_result"], "责令改正；警告")
        self.assertIsNone(case["fine_amount"])
        self.assertNotIn("吊销", case["violation"].split("违反本法规定")[0])
        self.assertIn("吊销许可证", case["regulation_text"])         # 法条原文单独保留，不丢
        # 种子数据里那条真实的幼儿园案也已按新规则改正
        seed = json.loads(config.OFFICIAL_SEED_FILE.read_text(encoding="utf-8"))["records"]
        kg = next(r for r in seed if "荔湾区" in r["case_title"] and "幼儿园" in r["case_title"])
        self.assertEqual(kg["handling_result"], "责令改正；警告")

    def test_2_restart_seed_does_not_overwrite_correction(self):
        seed = self._collect_then_revise()
        pipeline.load_seed(self.conn, seed)                        # 启动初始化时灌种子
        self.assertEqual((self._r8()["fine_amount"], self._r8()["revision"]), (60000, 2))

    def test_3_reparse_uses_latest_snapshot(self):
        self._collect_then_revise()
        n = self.conn.execute("SELECT COUNT(DISTINCT sha256) FROM source_snapshot WHERE url = %s",
                              (GZ_URL,)).fetchone()[0]
        self.assertGreaterEqual(n, 2)                              # 改稿前后两份快照都在
        pipeline.reparse_snapshots(self.conn, "gz_amr", snapshot_root=self.root)
        self.assertEqual((self._r8()["fine_amount"], self._r8()["revision"]), (60000, 2))

    def _topic(self, kw):
        return self.conn.execute("INSERT INTO topic(name, keywords, channels, brand, entities, event_rules, enabled) "
                                 "VALUES(%s, %s, '{}', %s, '[]', '[]', 1)",
                                 (kw + "监测", json.dumps([kw], ensure_ascii=False), kw)).lastrowid

    def test_4_store_added_later_gets_linked(self):
        tid = self._topic("汤粉王")
        self.conn.commit()
        pipeline.collect(self.conn, "gz_amr", fetch=FakeSite(), snapshot_root=self.root)
        q = "SELECT topic_id, store_id FROM official_record WHERE subject = '增城某汤粉王店'"
        self.assertEqual((one(self.conn, q)["topic_id"], one(self.conn, q)["store_id"]), (tid, None))
        sid = self.conn.execute("INSERT INTO store(topic_id, name, aliases, ownership) VALUES(%s,%s,%s,'加盟')",
                                (tid, "汤粉王·增城店", json.dumps(["增城某汤粉王店"], ensure_ascii=False))).lastrowid
        pipeline.link_records(self.conn)
        self.assertEqual(one(self.conn, q)["store_id"], sid)

    def test_5_license_subject_matches_without_brand_word(self):
        tid = self._topic("某个不出现的品牌")
        sid = self.conn.execute("INSERT INTO store(topic_id, name, aliases, ownership, license_subject) "
                                "VALUES(%s, '某品牌·加盟一店', '[]', '加盟', '刘某某')", (tid,)).lastrowid
        self.conn.commit()
        pipeline.collect(self.conn, "gz_amr", fetch=FakeSite(), snapshot_root=self.root)
        r = one(self.conn, "SELECT topic_id, store_id FROM official_record WHERE official_url = %s AND case_no = 1",
                (GZ_URL,))
        self.assertEqual((r["topic_id"], r["store_id"]), (tid, sid))

    def test_6_topic_with_store_or_official_cannot_be_deleted(self):
        from app.core.exceptions import Conflict
        from app.services import topic_service
        tid = self._topic("删除校验")
        sid = self.conn.execute("INSERT INTO store(topic_id, name, aliases, ownership) VALUES(%s, 'x店', '[]', '直营')",
                                (tid,)).lastrowid
        self.conn.commit()
        with self.assertRaises(Conflict):
            topic_service.delete(self.conn, tid)
        self.conn.execute("DELETE FROM store WHERE id = %s", (sid,))
        rid = self.conn.execute("SELECT id FROM official_record LIMIT 1").fetchone()["id"]
        self.conn.execute("UPDATE official_record SET topic_id = %s WHERE id = %s", (tid, rid))
        self.conn.commit()
        with self.assertRaises(Conflict):
            topic_service.delete(self.conn, tid)
        self.conn.execute("UPDATE official_record SET topic_id = NULL WHERE id = %s", (rid,))
        self.conn.commit()
        topic_service.delete(self.conn, tid)                       # 都清掉后可以删
        self.assertIsNone(one(self.conn, "SELECT id FROM topic WHERE id = %s", (tid,)))


class TestCodexRecheckStep2(unittest.TestCase):
    """Codex 第②步复审的 4 类问题（5 个场景），各有回归测试。借用上面的建库/清理和工具方法，不重跑那 6 条。"""

    setUpClass = TestCodexReviewStep2.__dict__["setUpClass"]
    setUp = TestCodexReviewStep2.setUp
    _r8 = TestCodexReviewStep2._r8
    _collect_then_revise = TestCodexReviewStep2._collect_then_revise
    _topic = TestCodexReviewStep2._topic

    def tearDown(self):
        self.conn.rollback()
        for tid in getattr(self, "_topics", []):
            self.conn.execute("DELETE FROM store WHERE topic_id = %s", (tid,))
            self.conn.execute("UPDATE official_record SET topic_id = NULL, store_id = NULL WHERE topic_id = %s", (tid,))
            self.conn.execute("DELETE FROM topic WHERE id = %s", (tid,))
        self.conn.commit()
        TestCodexReviewStep2.tearDown(self)

    def test_1_1_proposed_penalty_is_not_final(self):
        text = ("当事人未按规定开展食品安全自查。依据《中华人民共和国食品安全法》第一百二十六条第一款第（五）项的规定，"
                "广州市海珠区市场监督管理局拟依法对当事人作出罚款5000元的行政处罚。")
        self.assertEqual(gkmlpt.fines(gkmlpt.decision_text(text)), [])
        self.assertEqual(gkmlpt.proposed_result(text), "拟罚款5,000元（处罚告知阶段，非最终决定）")
        self.assertEqual(gkmlpt.proposed_result("该局发出行政处罚告知书，拟对当事人处200元罚款。"),
                         "拟罚款200元（处罚告知阶段，非最终决定）")
        seed = json.loads(config.OFFICIAL_SEED_FILE.read_text(encoding="utf-8"))["records"]
        hz = next(r for r in seed if r["record_key"].startswith("5685f644"))   # 真实的海珠幼儿园案
        self.assertIsNone(hz["fine_amount"])
        self.assertIn("拟罚款5,000元", hz["handling_result"])
        self.assertNotIn("；罚款5,000元", "；" + hz["handling_result"])

    def test_1_2_conditional_clause_after_semicolon_not_taken(self):
        text = ("经查，当事人销售超过保质期的食品。依据《食品安全法》第一百二十四条，对当事人罚款5000元；"
                "情节严重的，责令停产停业，直至吊销许可证。")
        result = gkmlpt.handling_result(gkmlpt.decision_text(text))
        self.assertEqual(result, "罚款5,000元")
        statute = "《食品安全法》第一百二十六条规定：处五千元以上五万元以下罚款；情节严重的，责令停产停业，直至吊销许可证。"
        self.assertEqual(gkmlpt.decision_text(statute), "")

    def test_2_same_license_subject_multiple_stores(self):
        north = {"id": 1, "topic_id": 9, "name": "汤粉王·北店", "aliases": [], "license_subject": "某餐饮有限公司"}
        south = {"id": 2, "topic_id": 9, "name": "汤粉王·南店", "aliases": [], "license_subject": "某餐饮有限公司"}
        m = pipeline._match_store
        self.assertIs(m([north, south], "某餐饮有限公司", "当事人南店后厨卫生不合格", 9), south)
        self.assertIs(m([north, south], "某餐饮有限公司", "当事人汤粉王·北店使用过期原料", None), north)
        self.assertIsNone(m([north, south], "某餐饮有限公司", "当事人后厨卫生不合格", None))   # 分不清：留空
        # 入库链路上：同主体两家店、正文没点名 → 只挂品牌不挂门店
        tid = self._topic("同主体品牌")
        self._topics = [tid]
        for n in ("同主体品牌·北店", "同主体品牌·南店"):
            self.conn.execute("INSERT INTO store(topic_id, name, aliases, ownership, license_subject) "
                              "VALUES(%s, %s, '[]', '加盟', '刘某某')", (tid, n))
        self.conn.commit()
        pipeline.collect(self.conn, "gz_amr", fetch=FakeSite(), snapshot_root=self.root)
        r = one(self.conn, "SELECT store_id FROM official_record WHERE official_url = %s AND case_no = 1", (GZ_URL,))
        self.assertIsNone(r["store_id"])

    def test_3_reparse_tie_on_fetched_at_with_mixed_citations(self):
        self._collect_then_revise()
        shas = [r["sha256"] for r in rows(self.conn, "SELECT sha256 FROM source_snapshot WHERE url = %s", (GZ_URL,))]
        new = one(self.conn, "SELECT snapshot_sha256 FROM official_record WHERE official_url = %s AND case_no = 8",
                  (GZ_URL,))["snapshot_sha256"]
        old = next(s for s in shas if s != new)
        # 模拟旧版留下的库：其它案件还引用旧快照，两份快照采集时间同秒
        self.conn.execute("UPDATE source_snapshot SET fetched_at = '2026-01-01 00:00:00' WHERE url = %s", (GZ_URL,))
        self.conn.execute("UPDATE official_record SET snapshot_sha256 = %s WHERE official_url = %s AND case_no <> 8",
                          (old, GZ_URL))
        pipeline.reparse_snapshots(self.conn, "gz_amr", snapshot_root=self.root)
        self.assertEqual((self._r8()["fine_amount"], self._r8()["revision"]), (60000, 2))

    def test_4_older_seed_of_same_snapshot_cannot_override_reparse(self):
        pipeline.collect(self.conn, "gz_amr", fetch=FakeSite(), snapshot_root=self.root)
        q = "SELECT handling_result, parser_version FROM official_record WHERE official_url = %s AND case_no = 1"
        good = one(self.conn, q, (GZ_URL,))
        self.assertEqual(good["parser_version"], gkmlpt.PARSER_VERSION)
        path = Path(self.root) / "stale_seed.json"
        pipeline.export_seed(self.conn, path)
        doc = json.loads(path.read_text(encoding="utf-8"))
        for r in doc["records"]:
            if r["official_url"] == GZ_URL and r["case_no"] == 1:
                r["handling_result"] = "停业整改；吊销许可"
        for version in (None, gkmlpt.PARSER_VERSION - 1, gkmlpt.PARSER_VERSION):   # 旧版/无版本/同版本：都不许覆盖
            for r in doc["records"]:
                r["parser_version"] = version
            path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
            pipeline.load_seed(self.conn, path)
            self.assertEqual(one(self.conn, q, (GZ_URL,))["handling_result"], good["handling_result"])
        for r in doc["records"]:
            r["parser_version"] = gkmlpt.PARSER_VERSION + 1                     # 更新规则的种子才刷新
        path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        pipeline.load_seed(self.conn, path)
        self.assertEqual(one(self.conn, q, (GZ_URL,))["handling_result"], "停业整改；吊销许可")


def _review_page(text: str, extra: str = "") -> bytes:
    return ("<html><body><p>发布日期：2026-11-23 浏览次数：</p>"
            "<p>一、复核餐饮有限公司从事餐饮服务违法行为案</p>"
            f"<p>案情：{text}</p>{extra}</body></html>").encode("utf-8")


class _IsolatedOfficialFixture:
    """隔离快照目录 + 用完清理的官方记录/品牌；给复审回归测试共用。"""

    @classmethod
    def setUpClass(cls):
        demo.reset()

    def setUp(self):
        self.conn = connect()
        self.root = tempfile.mkdtemp(prefix="snap_")
        self._urls, self._topics = [], []

    def tearDown(self):
        self.conn.rollback()
        for url in self._urls:
            self.conn.execute("DELETE FROM official_record WHERE official_url = %s", (url,))
        for tid in self._topics:
            self.conn.execute("DELETE FROM store WHERE topic_id = %s", (tid,))
            self.conn.execute("UPDATE official_record SET topic_id = NULL, store_id = NULL WHERE topic_id = %s", (tid,))
            self.conn.execute("DELETE FROM topic WHERE id = %s", (tid,))
        self.conn.commit()
        self.conn.close()

    def _collect(self, url, body):
        self._urls.append(url)
        stats = pipeline.collect(self.conn, "gz_amr", article_urls=[url], snapshot_root=self.root,
                                 fetch=lambda u: http.Response(u, 200, body, 1))
        self.assertEqual(stats["errors"], [])

    def _case(self, text):
        return gkmlpt.parse_article(_review_page(text), "http://x/case", GZ)["cases"][0]


class TestCodexRecheck2Step2(_IsolatedOfficialFixture, unittest.TestCase):
    """Codex 第②步第三轮复审的 4 个问题，各有回归测试；另补两条「拟」范围的边界。"""

    def test_1_proposal_list_keeps_scope_across_semicolons(self):
        case = self._case("该局向当事人送达行政处罚告知书，拟作出以下行政处罚：一、给予警告；二、罚款5000元。")
        self.assertIsNone(case["fine_amount"])
        self.assertEqual(case["investigation_status"], "拟处罚（已告知）")
        self.assertEqual(case["handling_result"], "拟罚款5,000元（处罚告知阶段，非最终决定）")
        # 分行列出的也一样
        lines = gkmlpt.decision_text("经查，当事人销售过期食品。该局拟作出如下处罚：\n一、给予警告；\n二、罚款5000元。")
        self.assertEqual(gkmlpt.fines(lines), [])

    def test_1b_final_decision_after_proposal_is_kept(self):
        text = ("该局拟作出以下行政处罚：一、给予警告；二、罚款5000元。当事人未提出陈述申辩，"
                "该局依法决定对当事人罚款5000元。")
        case = self._case(text)
        self.assertEqual(case["fine_amount"], 5000)
        self.assertEqual(case["investigation_status"], "已处罚")
        # 同一句里分号后出现实际决定，也结束「拟」的范围
        same = "该局拟作出以下处罚：一、警告；当事人放弃陈述申辩，该局决定罚款3000元。"
        self.assertEqual(gkmlpt.fines(gkmlpt.decision_text(same)), [3000])

    def test_2_affirmed_serious_fact_is_not_conditional(self):
        case = self._case("经调查认定，当事人的违法行为属于情节严重的情形，该局依法决定对当事人处以罚款50000元的行政处罚。")
        self.assertEqual(case["fine_amount"], 50000)
        self.assertEqual(case["investigation_status"], "已处罚")
        # 假设性罚则照旧不算
        self.assertEqual(gkmlpt.handling_result(gkmlpt.decision_text(
            "对当事人罚款5000元；情节严重的，责令停产停业，直至吊销许可证。")), "罚款5,000元")

    def test_3_reparse_uses_each_records_own_snapshot(self):
        url = "https://example.test/different-case-revisions"

        def two(first, second):
            return _review_page(f"该局依法决定对当事人罚款{first}元。",
                                "<p>二、复核第二餐饮公司从事餐饮服务违法行为案</p>"
                                f"<p>案情：该局依法决定对当事人罚款{second}元。</p>")
        bodies = [two(50000, 10000), two(60000, 10000), two(61000, 10000), two(61000, 20000)]
        for b in bodies:
            self._collect(url, b)
        shas = [hashlib.sha256(b).hexdigest() for b in bodies]
        # 旧版库：只有改了稿的案件换了快照引用；甲案先改两次、乙案后改一次，采集时间还打乱
        self.conn.execute("UPDATE official_record SET snapshot_sha256 = %s WHERE official_url = %s AND case_no = 1",
                          (shas[2], url))
        for i, sha in enumerate(reversed(shas)):
            self.conn.execute("UPDATE source_snapshot SET fetched_at = %s WHERE sha256 = %s",
                              (f"2026-11-23 16:00:0{i}", sha))
        self.conn.commit()
        q = "SELECT fine_amount, revision FROM official_record WHERE official_url = %s ORDER BY case_no"
        expect = [(61000, 3), (20000, 2)]
        self.assertEqual([(r["fine_amount"], r["revision"]) for r in rows(self.conn, q, (url,))], expect)
        pipeline.reparse_snapshots(self.conn, "gz_amr", snapshot_root=self.root)
        self.assertEqual([(r["fine_amount"], r["revision"]) for r in rows(self.conn, q, (url,))], expect)

    def test_4_old_wrong_store_link_is_reconciled(self):
        tid = self.conn.execute("INSERT INTO topic(name, keywords, channels, enabled) VALUES(%s, %s, '{}', 1)",
                                ("复查门店归属", json.dumps(["复查品牌"]))).lastrowid
        self._topics.append(tid)
        ids = [self.conn.execute("INSERT INTO store(topic_id, name, aliases, ownership, license_subject) "
                                 "VALUES(%s, %s, %s, '直营', '复核餐饮有限公司')",
                                 (tid, "复查品牌·" + side, json.dumps([side]))).lastrowid for side in ("北店", "南店")]
        self.conn.commit()
        url = "https://example.test/legacy-wrong-store"
        self._collect(url, _review_page("本案涉及复查品牌·南店，该局依法对当事人罚款5000元。"))
        q = "SELECT topic_id, store_id FROM official_record WHERE official_url = %s"
        self.assertEqual(one(self.conn, q, (url,))["store_id"], ids[1])
        self.conn.execute("UPDATE official_record SET store_id = %s WHERE official_url = %s", (ids[0], url))
        self.conn.commit()
        pipeline.load_seed(self.conn)
        pipeline.reparse_snapshots(self.conn, "gz_amr", snapshot_root=self.root)
        self.assertEqual(one(self.conn, q, (url,))["store_id"], ids[1])          # 旧版挂错北店 → 纠正到南店
        # 正文分不清是哪家店的旧链接：清空门店，品牌保留
        self.conn.execute("UPDATE official_record SET store_id = %s, violation = %s WHERE official_url = %s",
                          (ids[0], "该局依法对当事人罚款5000元。", url))
        pipeline.link_records(self.conn)
        self.assertEqual(one(self.conn, q, (url,)), {"topic_id": tid, "store_id": None})


class TestCodexRecheck3Step2(_IsolatedOfficialFixture, unittest.TestCase):
    """Codex 第②步第四轮复审的 4 类问题、6 个失败场景，各有回归测试；另补两条反向检查。"""

    def test_1_decision_document_reference_stays_proposed(self):
        case = self._case("该局拟作出以下行政处罚：一、给予警告；二、罚款5000元（具体以行政处罚决定书为准）。")
        self.assertIsNone(case["fine_amount"])
        self.assertEqual(case["investigation_status"], "拟处罚（已告知）")

    def test_2_unpunctuated_list_items_stay_proposed(self):
        case = self._case("该局拟作出以下行政处罚：</p><p>一、给予警告</p><p>二、罚款5000元。")
        self.assertIsNone(case["fine_amount"])
        self.assertEqual(case["investigation_status"], "拟处罚（已告知）")
        # 不是列表项的下一行不在拟的范围里
        case = self._case("该局拟作出以下行政处罚：</p><p>一、给予警告</p><p>该局依法决定罚款3000元。")
        self.assertEqual(case["fine_amount"], 3000)

    def test_3_final_decision_after_proposal_in_same_sentence(self):
        case = self._case("该局原拟罚款5000元，经陈述申辩后，最终决定罚款3000元。")
        self.assertEqual(case["fine_amount"], 3000)
        self.assertEqual(case["investigation_status"], "已处罚")
        self.assertNotIn("拟罚款", case["handling_result"])      # 原拟处罚已被取代，不再挂着

    def test_4_hypothetical_with_belongs_to_is_conditional(self):
        case = self._case("该局依法对当事人给予警告；如属于情节严重的，责令停业并吊销许可证。")
        self.assertEqual(case["handling_result"], "警告")

    def test_5_serious_offender_modifier_is_not_conditional(self):
        case = self._case("该局对情节严重的当事人依法作出罚款50000元的行政处罚。")
        self.assertEqual(case["fine_amount"], 50000)
        self.assertEqual(case["investigation_status"], "已处罚")
        # 真正的条件罚则仍排除
        case = self._case("该局依法给予警告。情节严重的，吊销食品经营许可证。")
        self.assertEqual(case["handling_result"], "警告")

    def test_6_uncited_existing_record_is_not_reverted(self):
        url = "https://example.test/recheck3-null-citation"
        self._urls.append(url)
        snapshot.save(self.conn, url, "gz_amr", _review_page("该局依法决定罚款50000元。"), root=self.root)
        source = pipeline.source_by_id("gz_amr")
        art = gkmlpt.parse_article(_review_page("该局依法决定罚款61000元。"), url, source)
        seed = Path(self.root) / "seed.json"
        seed.write_text(json.dumps({"records": [pipeline.build_record(source, art, art["cases"][0], None)]},
                                   ensure_ascii=False), encoding="utf-8")
        self.assertEqual(pipeline.load_seed(self.conn, seed), 1)
        self.conn.commit()
        q = "SELECT fine_amount, revision FROM official_record WHERE official_url = %s"
        before = one(self.conn, q, (url,))
        pipeline.reparse_snapshots(self.conn, "gz_amr", snapshot_root=self.root)
        self.assertEqual(one(self.conn, q, (url,)), before)


def _real_seed_case(prefix):
    """随仓库种子里的真实案件，从它引用的快照原文重新解析（快照 hash 先核对）。"""
    rec = next(r for r in json.loads(config.OFFICIAL_SEED_FILE.read_text(encoding="utf-8"))["records"]
               if r["record_key"].startswith(prefix))
    sha = rec["snapshot_sha256"]
    body = (config.BACKEND_DIR / "data" / "snapshots" / sha[:2] / f"{sha}.html").read_bytes()
    assert hashlib.sha256(body).hexdigest() == sha
    source = pipeline.source_by_id(rec["source_id"])
    art = gkmlpt.parse_article(body, rec["official_url"], source)
    return rec, source, art, next(c for c in art["cases"] if c["case_no"] == rec["case_no"])


class TestCodexRecheck4Step2(_IsolatedOfficialFixture, unittest.TestCase):
    """Codex 第②步第五轮复审：真实样本里的 3 类存量错误（分公司主体、多笔罚款、处理日期）。"""

    def test_1_branch_company_subject_is_kept(self):
        for prefix, branch in [("c0f17841b4", "广州某日式料理餐饮有限公司悠方分公司"),
                               ("2520650800", "广州某餐饮投资有限公司悦和方分公司")]:
            with self.subTest(prefix=prefix):
                self.assertEqual(_real_seed_case(prefix)[3]["subject"], branch)
        # 总公司本身（标题后面没有分公司）不受影响
        self.assertEqual(gkmlpt.subject_of("广州某餐饮有限公司未主动提示防止食品浪费案"), "广州某餐饮有限公司")

    def test_2_branch_case_links_to_branch_store(self):
        from app.services import store_service
        rec, source, art, case = _real_seed_case("c0f17841b4")
        tid = self.conn.execute("INSERT INTO topic(name, keywords, channels, enabled) VALUES(%s, %s, '{}', 1)",
                                ("复核日式料理", json.dumps(["某日式料理"]))).lastrowid
        self._topics.append(tid)
        parent, branch = [store_service.create(self.conn, {
            "topic_id": tid, "name": name, "aliases": [], "ownership": "直营", "status": "营业",
            "license_subject": subject}) for name, subject in [
            ("复核日式料理·总店", "广州某日式料理餐饮有限公司"),
            ("复核日式料理·悠方店", "广州某日式料理餐饮有限公司悠方分公司")]]
        pipeline.upsert_record(self.conn, pipeline.build_record(source, art, case, rec["snapshot_sha256"]))
        pipeline.link_records(self.conn)
        got = one(self.conn, "SELECT store_id FROM official_record WHERE record_key = %s", (rec["record_key"],))
        self.assertEqual(got["store_id"], branch["id"])

    def test_3_separate_fines_are_summed(self):
        case = _real_seed_case("9db1df5670")[3]
        self.assertEqual(case["fine_amount"], 75000)
        self.assertEqual(case["handling_result"], "罚款75,000元（70,000+5,000）")
        # 复述已罚金额不重复计；公告自己写了合计的以合计为准
        self.assertEqual(self._case("该局依法对当事人罚款5000元。当事人已缴纳罚款5000元。")["fine_amount"], 5000)
        self.assertEqual(self._case("该局分别对两项违法行为罚款3000元、罚款2000元，合计罚款5000元。")["fine_amount"], 5000)

    def test_4_inspection_date_is_not_decision_date(self):
        self.assertIsNone(_real_seed_case("934e18abb0")[3]["decided_at"])          # 只有抽检日期
        self.assertIsNone(self._case("2023年5月9日，执法人员检查发现当事人未张贴标识，该局责令改正。")["decided_at"])
        self.assertIsNone(self._case("该局依法给予警告。")["decided_at"])           # 不拿发布日期充数
        # 写在决定行为上的日期照常识别；整改期限、违法发生日期不算
        self.assertEqual(_real_seed_case("13a772cf69")[3]["decided_at"], "2025-11-19")
        self.assertEqual(_real_seed_case("5685f64480")[3]["decided_at"], "2023-12-06")
        self.assertIsNone(self._case("该局当场责令当事人于2023年4月10日前改正。")["decided_at"])


class TestCodexRecheck5Step2(_IsolatedOfficialFixture, unittest.TestCase):
    """Codex 第②步第六轮复审：检查当天「当场责令改正/给予警告」的处理日期不能跟着检查日期一起被排除。"""

    def test_1_on_spot_decision_takes_inspection_date(self):
        for prefix, day in [("453f2f0e6a", "2023-03-24"),      # 白云区某餐厅，post_8895614 第一案
                            ("931669f9b8", "2023-05-10"),      # post_8980755
                            ("2520650800", "2023-03-27"),      # 悦和方分公司，post_8937131
                            ("096c21021e", "2023-04-07")]:     # 当场警告 + 4月10日前整改期限 + 4月11日复查
            with self.subTest(prefix=prefix):
                self.assertEqual(_real_seed_case(prefix)[3]["decided_at"], day)

    def test_2_on_spot_rule_does_not_reopen_inspection_dates(self):
        # 只有检查/抽检、没有「当场」决定的，仍留空
        self.assertIsNone(_real_seed_case("934e18abb0")[3]["decided_at"])
        self.assertIsNone(self._case("2023年5月9日，执法人员检查发现当事人未张贴标识，该局责令改正。")["decided_at"])
        # 「当场」前面只有整改期限或只到月份的日期，不算
        self.assertIsNone(self._case("该局当场责令当事人于2023年4月10日前改正。")["decided_at"])
        self.assertIsNone(self._case("2023年5月，执法人员检查发现问题，该局当场责令改正。")["decided_at"])
        self.assertEqual(self._case("2023年5月9日，执法人员检查发现当事人未张贴标识。该局当场责令改正，并给予警告。")
                         ["decided_at"], "2023-05-09")

    def test_3_seed_dates_match_reparse(self):
        seed = json.loads(config.OFFICIAL_SEED_FILE.read_text(encoding="utf-8"))["records"]
        self.assertEqual(sum(r["decided_at"] is not None for r in seed), 30)
        for r in seed:
            with self.subTest(record=r["record_key"][:10]):
                self.assertEqual(_real_seed_case(r["record_key"][:10])[3]["decided_at"], r["decided_at"])


class TestCodexRecheck6Step2(_IsolatedOfficialFixture, unittest.TestCase):
    """Codex 第②步第七轮复审：「当场」决定只取检查事件的日期，生产日期、保质期、整改期限、举报日期都不算。"""

    def test_1_on_spot_skips_attribute_and_report_dates(self):
        on_spot = "该局当场责令改正，并给予警告。"
        for text, day in [
            ("检查发现，店内食品生产日期为2023年3月20日，已超过保质期。", None),
            ("2023年3月24日，执法人员检查发现，店内食品生产日期为2023年3月20日，已超过保质期。", "2023-03-24"),
            ("2023年3月24日，执法人员检查发现，店内食品保质期至2023年3月20日，已超过保质期。", "2023-03-24"),
            ("2023年3月24日，执法人员检查发现问题，整改期限为2023年3月28日。", "2023-03-24"),
            ("2023年3月20日，监管局收到举报。后经现场检查发现餐厅未主动提示消费者，", None),
        ]:
            with self.subTest(text=text):
                self.assertEqual(self._case(text + on_spot)["decided_at"], day)

    def test_2_seed_parser_version(self):
        seed = json.loads(config.OFFICIAL_SEED_FILE.read_text(encoding="utf-8"))["records"]
        self.assertEqual({r["parser_version"] for r in seed}, {gkmlpt.PARSER_VERSION})
