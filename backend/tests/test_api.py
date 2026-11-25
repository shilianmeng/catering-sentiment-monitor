"""接口集成测试：在后台线程起 uvicorn（随机空闲端口，不碰 8000/8091），用 urllib 调接口。

本机没装 httpx，所以不用 FastAPI 的 TestClient。
"""
import json
import socket
import threading
import time
import unittest
import urllib.error
import urllib.request

import uvicorn

import tests  # Initialize the isolated database even when discovery omits -t .

from app.engine import demo
from app.db.session import connect
from app.main import app


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        demo.reset()
        cls.port = free_port()
        assert cls.port not in (8000, 8091)
        cls.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=cls.port, log_level="warning"))
        cls.thread = threading.Thread(target=cls.server.run, daemon=True)
        cls.thread.start()
        for _ in range(100):
            if cls.server.started:
                break
            time.sleep(0.05)
        cls.tokens = {u: cls.call("POST", "/api/v1/login", {"username": u, "password": "123456"})[1]["token"]
                      for u in ("analyst", "pr", "admin")}

    @classmethod
    def tearDownClass(cls):
        cls.server.should_exit = True
        cls.thread.join(timeout=5)

    @classmethod
    def call(cls, method, path, body=None, user=None, raw=False):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(f"http://127.0.0.1:{cls.port}{path}", data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        if user:
            req.add_header("Authorization", "Bearer " + cls.tokens[user])
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                payload = r.read()
                return r.status, (payload if raw else json.loads(payload or b"null"))
        except urllib.error.HTTPError as e:
            payload = e.read()
            try:
                return e.code, json.loads(payload)
            except ValueError:
                return e.code, payload

    # ---- 登录与权限 ----

    def test_login_and_auth(self):
        code, _ = self.call("POST", "/api/v1/login", {"username": "pr", "password": "wrong"})
        self.assertEqual(code, 401)
        code, _ = self.call("GET", "/api/v1/overview")
        self.assertEqual(code, 401)
        code, me = self.call("GET", "/api/v1/me", user="pr")
        self.assertEqual((code, me["role"]), (200, "pr"))

    def test_role_permissions(self):
        # 公关不能改级、不能建主题、不能改配置；分析师不能处置
        self.assertEqual(self.call("POST", "/api/v1/events/ev002/level", {"level": "B", "reason": "x"}, "pr")[0], 403)
        self.assertEqual(self.call("POST", "/api/v1/topics", {"name": "t", "keywords": "a"}, "pr")[0], 403)
        self.assertEqual(self.call("PUT", "/api/v1/config", {"silence_minutes": 30}, "analyst")[0], 403)
        self.assertEqual(self.call("POST", "/api/v1/events/ev002/disposal", {"to_status": "跟踪中"}, "analyst")[0], 403)

    # ---- 运维与统一错误格式（前后端分离后后端不再提供页面） ----

    def test_health_and_error_envelope(self):
        code, h = self.call("GET", "/health")
        self.assertEqual((code, h["status"]), (200, "ok"))
        code, d = self.call("GET", "/api/v1/events/ev999", user="analyst")
        self.assertEqual((code, d["code"]), (404, 404))
        self.assertIn("不存在", d["message"])
        code, d = self.call("GET", "/api/v1/contents?page=abc", user="analyst")
        self.assertEqual((code, d["code"]), (422, 422))
        code, d = self.call("PUT", "/api/v1/config", {"level_s": 101}, "admin")
        self.assertEqual(code, 422)                         # 超出取值范围
        self.assertEqual(self.call("GET", "/", raw=True)[0], 404)

    # ---- 大盘 / 内容 ----

    def test_overview_and_contents(self):
        code, d = self.call("GET", "/api/v1/overview", user="analyst")
        self.assertEqual(code, 200)
        self.assertIn("negative_rate", d["metrics"])
        code, page = self.call("GET", "/api/v1/contents?page_size=5", user="analyst")
        self.assertEqual(code, 200)
        self.assertLessEqual(len(page["items"]), 5)
        code, page = self.call("GET", "/api/v1/contents?keyword=%E9%A6%99%E6%BB%A1%E5%9B%AD", user="analyst")
        self.assertGreater(page["total"], 0)

    # ---- 处置状态机 ----

    def test_disposal_state_machine(self):
        eid = "ev002"
        code, d = self.call("POST", f"/api/v1/events/{eid}/disposal", {"to_status": "已处理"}, "pr")
        self.assertEqual(code, 400)                       # 待处理不能跳到已处理
        self.assertIn("只能流转到", d["detail"])
        self.assertEqual(self.call("POST", f"/api/v1/events/{eid}/disposal", {"to_status": "跟踪中"}, "pr")[0], 200)
        code, d = self.call("POST", f"/api/v1/events/{eid}/disposal", {"to_status": "忽略", "note": "非负面"}, "admin")
        self.assertEqual(code, 200)                       # 忽略可从任意未结束状态进入
        self.assertEqual(d["next_statuses"], [])
        code, d = self.call("POST", f"/api/v1/events/{eid}/disposal", {"to_status": "跟踪中"}, "pr")
        self.assertEqual(code, 400)                       # 已结束不能再流转
        code, log = self.call("GET", f"/api/v1/events/{eid}/disposals", user="pr")
        self.assertEqual([x["to_status"] for x in log], ["跟踪中", "忽略"])

    # ---- 人工改级 ----

    def test_manual_level(self):
        code, d = self.call("POST", "/api/v1/events/ev001/level", {"level": "S", "reason": ""}, "analyst")
        self.assertEqual(code, 400)
        code, ev = self.call("POST", "/api/v1/events/ev001/level", {"level": "S", "reason": "媒体关注度高"}, "analyst")
        self.assertEqual((code, ev["level"], ev["manual_override"]), (200, "S", 1))
        code, ev = self.call("POST", "/api/v1/events/ev001/level", {"level": "auto", "reason": "恢复"}, "admin")
        self.assertEqual(ev["manual_override"], 0)
        code, ev = self.call("GET", "/api/v1/events/ev001", user="analyst")
        self.assertEqual(len(ev["level_adjustments"]), 2)

    # ---- 草案与报告 ----

    def test_draft_report_export(self):
        code, dr = self.call("POST", "/api/v1/events/ev001/response-draft", user="pr")
        self.assertEqual((code, dr["gen_mode"]), (200, "模板生成"))
        code, dr = self.call("POST", "/api/v1/events/ev001/draft-adopt", {}, "pr")
        self.assertEqual((code, dr["adopted"]), (200, 1))
        code, rep = self.call("POST", "/api/v1/events/ev001/report", user="analyst")
        self.assertEqual(code, 200)
        self.assertIn("# ", rep["markdown"])
        code, md = self.call("GET", f"/api/v1/reports/{rep['id']}/export?format=md", user="pr", raw=True)
        self.assertEqual(code, 200)
        self.assertIn("香满园".encode(), md)
        code, pdf = self.call("GET", f"/api/v1/reports/{rep['id']}/export?format=pdf", user="pr", raw=True)
        if code == 500:
            self.skipTest("本机无中文字体，PDF 导出跳过")
        self.assertEqual(code, 200)
        self.assertTrue(pdf.startswith(b"%PDF"))

    # ---- 配置 ----

    def test_config_validation(self):
        code, d = self.call("PUT", "/api/v1/config", {"level_a": 90}, "admin")
        self.assertEqual(code, 400)                        # 必须 S > A > B
        code, d = self.call("PUT", "/api/v1/config", {"kol_alert_weight": 9, "notify_email": True}, "admin")
        self.assertEqual((code, d["kol_alert_weight"], d["notify_email"]), (200, 9, True))

    # ---- 主题 CRUD ----

    def test_topic_crud(self):
        code, t = self.call("POST", "/api/v1/topics", {"name": "测试主题", "keywords": "甲，乙, 丙"}, "analyst")
        self.assertEqual((code, t["keywords"]), (200, ["甲", "乙", "丙"]))
        code, t = self.call("PUT", f"/api/v1/topics/{t['id']}", {"channels": {"行业论坛": False}}, "analyst")
        self.assertFalse(t["channels"]["行业论坛"])
        self.assertTrue(t["channels"]["社交媒体"])
        self.assertEqual(self.call("DELETE", f"/api/v1/topics/{t['id']}", user="admin")[0], 200)

    # ---- 演示时钟 ----

    def test_demo_advance(self):
        code, r = self.call("POST", "/api/v1/demo/advance", {"batches": 1}, "admin")
        self.assertEqual(code, 200)
        self.assertIn("current_label", r)
        # 声量曲线只到当前批次，未到的批次不出现
        code, ev = self.call("GET", "/api/v1/events/ev001", user="analyst")
        self.assertEqual(len(ev["series"]), r["current_batch"] + 1)

    def test_demo_control_permissions(self):
        before = self.call("GET", "/api/v1/overview", user="admin")[1]
        for path in ("/api/v1/demo/reset", "/api/v1/demo/advance"):
            for user, expected in ((None, 401), ("analyst", 403), ("pr", 403)):
                self.assertEqual(self.call("POST", path, {}, user)[0], expected)
        self.assertEqual(self.call("GET", "/api/v1/overview", user="admin")[1], before)
        self.assertEqual(self.call("POST", "/api/v1/demo/reset", {}, "admin")[0], 200)

    def test_topic_delete_references(self):
        for table in ("content", "event"):
            with self.subTest(table=table):
                code, topic = self.call("POST", "/api/v1/topics",
                                        {"name": "关联保护", "keywords": "保护"}, "admin")
                self.assertEqual(code, 200)
                tid = topic["id"]
                conn = connect()
                try:
                    row = conn.execute(f"SELECT id, topic_id FROM {table} LIMIT 1").fetchone()
                    conn.execute(f"UPDATE {table} SET topic_id = %s WHERE id = %s", (tid, row["id"]))
                    conn.commit()
                    self.assertEqual(self.call("DELETE", f"/api/v1/topics/{tid}", user="admin")[0], 409)
                    self.assertIsNotNone(conn.execute("SELECT id FROM topic WHERE id = %s", (tid,)).fetchone())
                    self.assertEqual(conn.execute(f"SELECT topic_id FROM {table} WHERE id = %s",
                                                  (row["id"],)).fetchone()[0], tid)
                finally:
                    conn.execute(f"UPDATE {table} SET topic_id = %s WHERE id = %s", (row["topic_id"], row["id"]))
                    conn.commit()
                    conn.close()
                self.assertEqual(self.call("DELETE", f"/api/v1/topics/{tid}", user="admin")[0], 200)


if __name__ == "__main__":
    unittest.main()
