"""每次测试创建独立 MySQL 库，结束删除；不使用正式业务库。"""
import atexit
import os
import sys
import uuid
from pathlib import Path
import pymysql

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if "app.core.config" in sys.modules:
    raise RuntimeError("请在导入 app 前加载 tests，避免误用业务库")

# 设为空串让 config 里写好的 key 失效，测试一律走模板，不调用真实模型
os.environ["OPENAI_API_KEY"] = ""
os.environ["YUQING_LOG_LEVEL"] = "WARNING"     # 测试时不刷访问日志
os.environ["YUQING_ENV"] = "test"
_name = "yuqing_test_" + uuid.uuid4().hex
os.environ["YUQING_MYSQL_DATABASE"] = _name
# 采集快照写到临时目录，不污染 backend/data/snapshots
import tempfile
_snap_dir = tempfile.TemporaryDirectory(prefix="yuqing_snap_")
os.environ["YUQING_SNAPSHOT_DIR"] = _snap_dir.name
from app.core.config import MYSQL
_options = {k: v for k, v in MYSQL.items() if k != "database"}
_admin = pymysql.connect(**_options, charset="utf8mb4", autocommit=True)
with _admin.cursor() as cursor:
    cursor.execute(f"CREATE DATABASE `{_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_bin")

def _cleanup():
    try:
        with _admin.cursor() as cursor:
            cursor.execute(f"DROP DATABASE `{_name}`")
    finally:
        _admin.close()

atexit.register(_cleanup)
