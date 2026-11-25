"""客户画像、登录会话、口令哈希的测试。

三件事各一条：换一个客户品牌只改数据不改代码；服务重启不掉登录；新口令用 PBKDF2，
老库里的无盐 SHA-256 还能登进来。
"""
import hashlib
import unittest

import tests  # noqa: F401 —— 先初始化隔离测试库

from app.core.security import TokenStore, hash_password, needs_rehash, verify_password
from app.db.session import connect, one
from app.engine import dedup, demo
from app.services import topic_service


class TestTenantProfile(unittest.TestCase):
    """一个客户总部一条主题：品牌、门店、议题规则都在数据里。"""

    @classmethod
    def setUpClass(cls):
        demo.reset()

    def test_default_brand_from_keywords(self):
        conn = connect()
        try:
            topic = topic_service.create(conn, {"name": "李记烤肉", "keywords": "李记，李记烤肉"},
                                         {"username": "admin"})
            self.assertEqual(topic["brand"], "李记")
            self.assertEqual(topic["keywords"], ["李记", "李记烤肉"])
            self.assertEqual(topic["entities"], [])          # 没配就空着，引擎走行业默认规则
            topic_service.delete(conn, topic["id"])
        finally:
            conn.close()

    def test_custom_rules_drive_event_title(self):
        conn = connect()
        topic = None
        try:
            topic = topic_service.create(conn, {
                "name": "测试面馆监测",
                "keywords": ["测试面馆"],
                "brand": "测试面馆",
                "entities": [{"name": "测试面馆·人民路店", "type": "门店", "aliases": ["人民路店"]}],
                "event_rules": [{"category": "异物", "title": "{brand}·面条异物事件",
                                 "keywords": ["异物", "虫子"]}],
            }, {"username": "admin"})
            item = {"id": "t001", "text": "测试面馆人民路店的面里吃出虫子", "parent_id": None}
            eid = dedup.assign_event(conn, item, item["text"], topic, "2026-11-18 12:00")
            ev = one(conn, "SELECT * FROM event WHERE id = %s", (eid,))
            self.assertEqual(ev["title"], "测试面馆·面条异物事件")
            self.assertEqual(ev["topic_id"], topic["id"])

            # 不提这个品牌的内容不会被归到这家客户名下
            other = {"id": "t002", "text": "隔壁那家面里也有虫子", "parent_id": None}
            self.assertIsNone(dedup.assign_event(conn, other, other["text"], topic, "2026-11-18 12:00"))
            conn.rollback()
        finally:
            if topic:
                topic_service.delete(conn, topic["id"])
            conn.close()

    def test_partial_update_keeps_other_fields(self):
        conn = connect()
        try:
            topic = topic_service.create(conn, {"name": "张记粥铺", "keywords": "张记"},
                                         {"username": "admin"})
            updated = topic_service.update(conn, topic["id"], {"brand": "张记粥铺"})
            self.assertEqual((updated["brand"], updated["name"]), ("张记粥铺", "张记粥铺"))
            self.assertEqual(updated["keywords"], ["张记"])
            topic_service.delete(conn, topic["id"])
        finally:
            conn.close()


class TestSessionPersistence(unittest.TestCase):
    def test_token_survives_restart(self):
        demo.reset()
        user = {"username": "analyst", "role": "analyst", "display_name": "分析师·小林"}
        token = TokenStore(3600).issue(user)

        # 新实例没有内存缓存，等价于服务重启：只能靠 auth_session 表认人
        restarted = TokenStore(3600)
        self.assertEqual(restarted.get(token)["username"], "analyst")

        restarted.revoke(token)
        self.assertIsNone(TokenStore(3600).get(token))

    def test_bad_token_rejected(self):
        demo.reset()
        self.assertIsNone(TokenStore(3600).get("not-a-real-token"))
        self.assertIsNone(TokenStore(3600).get(""))


class TestPasswordHash(unittest.TestCase):
    def test_pbkdf2_hash(self):
        h = hash_password("123456")
        self.assertTrue(h.startswith("pbkdf2_sha256$"))
        self.assertNotIn("123456", h)
        self.assertTrue(verify_password("123456", h))
        self.assertFalse(verify_password("1234567", h))
        self.assertFalse(needs_rehash(h))

    def test_legacy_sha256_still_verifies(self):
        legacy = hashlib.sha256("123456".encode("utf-8")).hexdigest()
        self.assertTrue(verify_password("123456", legacy))
        self.assertFalse(verify_password("bad", legacy))
        self.assertTrue(needs_rehash(legacy))


if __name__ == "__main__":
    unittest.main()
