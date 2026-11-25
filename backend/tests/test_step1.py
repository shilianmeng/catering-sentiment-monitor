"""第 ① 步：品牌去写死（一个品牌 = 一个 topic）、凭据外置、会话持久化、旧库升级。"""
import hashlib
import json
import re
import time
import unittest
from pathlib import Path

import tests  # noqa: F401  先初始化隔离测试库

from app.core import config
from app.core.security import TokenStore, hash_password, verify_password
from app.db.session import connect, migrate, one
from app.engine import collector, dedup, demo, profile
from app.engine.tagging import extract_entities, tag

BACKEND = Path(__file__).resolve().parent.parent

NOODLE = {  # 一个没有任何自定义画像的新品牌：只给品牌名，其余全走行业默认
    "id": 99, "name": "老王面馆监测", "brand": "老王面馆", "keywords": ["老王面馆", "老王"],
    "channels": {s: True for s in config.SOURCE_TYPES}, "enabled": 1,
    "entities": [{"name": "老王面馆·人民路店", "type": "门店", "aliases": ["人民路店"]}],
    "event_rules": [],
}


class TestNoHardcodedBrand(unittest.TestCase):
    def test_engine_code_has_no_brand_literals(self):
        """引擎、服务、接口代码里不再出现演示品牌或真实品牌名；品牌只出现在种子数据里。"""
        banned = ["香满园", "幸福路", "鸡腿堡", "海底捞", "寿司郎", "蜜雪冰城"]
        for py in (BACKEND / "app").rglob("*.py"):
            text = py.read_text(encoding="utf-8")
            for word in banned:
                self.assertNotIn(word, text, f"{py.relative_to(BACKEND)} 写死了「{word}」")

    def test_demo_brand_comes_from_seed_file(self):
        names = [t["brand"] for t in demo.seed_topics()]
        self.assertEqual(names, ["香满园"])

    def test_new_brand_uses_default_rules(self):
        rule = profile.match_rule(NOODLE, "老王面馆人民路店后厨有老鼠，地上全是油污")
        self.assertEqual(rule["category"], "后厨卫生")
        self.assertEqual(profile.render_title(NOODLE, rule), "老王面馆·后厨卫生问题")
        self.assertIsNone(profile.match_rule(NOODLE, "别家店后厨有老鼠"))   # 没提品牌不归类

    def test_store_and_brand_entities_from_topic(self):
        names = [e["name"] for e in extract_entities("老王人民路店被市场监管局责令整改", topic=NOODLE)]
        self.assertEqual(names[:2], ["老王面馆", "老王面馆·人民路店"])
        self.assertIn("市场监管局", names)
        self.assertEqual(profile.store_in(NOODLE, "老王面馆·人民路店后厨问题"), "老王面馆·人民路店")
        # 不传 topic 时只认行业通用实体，认不出任何品牌
        self.assertNotIn("老王面馆", [e["name"] for e in tag({"text": "老王面馆后厨有老鼠"})["entities"]])

    def test_two_brands_never_share_an_event(self):
        demo.reset()
        conn = connect()
        try:
            demo_topic = one(conn, "SELECT * FROM topic ORDER BY id LIMIT 1")
            cur = conn.execute(
                "INSERT INTO topic(name, keywords, channels, enabled, brand, entities, event_rules) "
                "VALUES(%s,%s,%s,1,%s,%s,%s)",
                (NOODLE["name"], json.dumps(NOODLE["keywords"], ensure_ascii=False),
                 json.dumps(NOODLE["channels"], ensure_ascii=False), NOODLE["brand"],
                 json.dumps(NOODLE["entities"], ensure_ascii=False), "[]"))
            noodle = one(conn, "SELECT * FROM topic WHERE id = %s", (cur.lastrowid,))
            item = {"id": "x-noodle-1", "text": "老王面馆后厨卫生太差了，有老鼠"}
            eid = dedup.assign_event(conn, item, item["text"], noodle, "2026-11-18 12:00")
            ev = one(conn, "SELECT * FROM event WHERE id = %s", (eid,))
            self.assertEqual(ev["topic_id"], noodle["id"])
            self.assertEqual(ev["title"], "老王面馆·后厨卫生问题")
            self.assertNotEqual(ev["topic_id"], demo_topic["id"])
            matched = collector.match_topic([demo_topic, noodle], {"source_type": "社交媒体"}, item["text"])
            self.assertEqual(matched["id"], noodle["id"])
            conn.rollback()
        finally:
            conn.close()


class TestSecrets(unittest.TestCase):
    def test_no_api_key_in_source(self):
        for py in (BACKEND / "app").rglob("*.py"):
            self.assertIsNone(re.search(r"sk-[A-Za-z0-9_-]{20,}", py.read_text(encoding="utf-8")), str(py))

    def test_secrets_file_is_gitignored_and_example_is_empty(self):
        ignore = (BACKEND.parent / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("secrets.local.json", ignore)
        example = json.loads((BACKEND / "secrets.example.json").read_text(encoding="utf-8"))
        self.assertEqual(example["openai_api_key"], "")


class TestPasswords(unittest.TestCase):
    def test_salted_and_verifiable(self):
        a, b = hash_password("123456"), hash_password("123456")
        self.assertNotEqual(a, b)                       # 每次随机盐
        self.assertTrue(verify_password("123456", a))
        self.assertFalse(verify_password("1234567", a))

    def test_legacy_sha256_still_verifies(self):
        legacy = hashlib.sha256(b"123456").hexdigest()
        self.assertTrue(verify_password("123456", legacy))
        self.assertFalse(verify_password("x", legacy))


class TestPersistentSessions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        demo.ensure_db()

    def test_survives_restart_and_stores_only_hash(self):
        token = TokenStore(3600).issue({"username": "analyst", "role": "analyst", "display_name": "x"})
        restarted = TokenStore(3600)                    # 新实例 = 进程重启后
        self.assertEqual(restarted.get(token)["role"], "analyst")
        conn = connect()
        try:
            self.assertIsNone(one(conn, "SELECT 1 x FROM auth_session WHERE token_hash = %s", (token,)))
            self.assertIsNotNone(one(conn, "SELECT 1 x FROM auth_session WHERE token_hash = %s",
                                     (hashlib.sha256(token.encode()).hexdigest(),)))
        finally:
            conn.close()
        restarted.revoke(token)
        self.assertIsNone(TokenStore(3600).get(token))

    def test_expired_token_rejected(self):
        store = TokenStore(-1)
        token = store.issue({"username": "pr", "role": "pr", "display_name": "x"})
        self.assertIsNone(store.get(token))
        self.assertIsNone(store.get(""))

    def test_session_survives_demo_reset(self):
        token = TokenStore(3600).issue({"username": "admin", "role": "admin", "display_name": "x"})
        demo.reset()
        self.assertEqual(TokenStore(3600).get(token)["username"], "admin")


class TestMigration(unittest.TestCase):
    def test_old_db_gets_new_columns_and_demo_profile(self):
        demo.reset()
        conn = connect()
        try:
            for col in ("brand", "entities", "event_rules"):
                conn.execute(f"ALTER TABLE topic DROP COLUMN `{col}`")
            conn.commit()
            migrate(conn)
            cols = {r["COLUMN_NAME"] for r in conn.execute(
                "SELECT COLUMN_NAME FROM information_schema.columns "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'topic'").fetchall()}
            self.assertTrue({"brand", "entities", "event_rules"} <= cols)
        finally:
            conn.close()
        demo.ensure_db()                                # 旧库启动：补画像
        conn = connect()
        try:
            t = one(conn, "SELECT * FROM topic ORDER BY id LIMIT 1")
            self.assertEqual(t["brand"], "香满园")
            self.assertTrue(any(e["type"] == "门店" for e in t["entities"]))
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
