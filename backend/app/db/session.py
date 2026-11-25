"""数据库访问：连接、建表/升级（migrate）、建库、配置读写、行转字典。"""
import json

import pymysql
from pymysql.cursors import DictCursor
import threading

from ..core import config
from .models import COLUMN_MIGRATIONS, DDL, KEEP_ON_RESET, TABLES

# 推进时钟、重置等写流程用这把锁串行化
write_lock = threading.RLock()

JSON_FIELDS = {
    "keywords", "channels", "entities", "event_rules", "score_basis", "sensitive_hits",
    "representative_content_ids", "notified", "sections", "disposal_log", "aliases", "legal_basis",
}


class Row(dict):
    """Preserve the existing named and positional row access."""
    def __getitem__(self, key):
        return tuple(self.values())[key] if isinstance(key, int) else super().__getitem__(key)


class Cursor(DictCursor):
    dict_type = Row


class Connection(pymysql.connections.Connection):
    def execute(self, sql, params=None):
        cursor = self.cursor()
        cursor.execute(sql, params)
        return cursor


def connect():
    return Connection(**config.MYSQL, charset="utf8mb4", cursorclass=Cursor,
                      autocommit=False, connect_timeout=10,
                      init_command="SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED")


def ensure_database():
    """库不存在就建（首次部署、换机器时用）；已存在则什么都不做。"""
    options = dict(config.MYSQL)
    name = options.pop("database")
    conn = pymysql.connect(**options, charset="utf8mb4", autocommit=True, connect_timeout=10)
    try:
        conn.cursor().execute(
            f"CREATE DATABASE IF NOT EXISTS `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_bin")
    finally:
        conn.close()


def _columns(conn, table):
    return {r["COLUMN_NAME"].lower() for r in conn.execute(
        "SELECT COLUMN_NAME FROM information_schema.columns "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s", (table,))}


def migrate(conn):
    """幂等升级：缺表建表、缺列补列，不动已有数据。启动时和测试里都调这个。"""
    for statement in DDL.split(";"):
        if statement.strip():
            conn.execute(statement)
    for table, columns in COLUMN_MIGRATIONS.items():
        existing = _columns(conn, table)
        for name, ddl_type in columns:
            if name.lower() not in existing:
                conn.execute(f"ALTER TABLE `{table}` ADD COLUMN `{name}` {ddl_type}")
    conn.commit()


def init_schema(conn):
    migrate(conn)


def drop_all(conn):
    """重建业务表；登录会话表保留（重置演示不该把所有人踢下线）。"""
    for t in TABLES:
        if t in KEEP_ON_RESET:
            continue
        conn.execute(f"DROP TABLE IF EXISTS `{t}`")
    conn.commit()


def row_to_dict(row):
    if row is None:
        return None
    d = dict(row)
    for k in JSON_FIELDS:
        if k in d and isinstance(d[k], str):
            try:
                d[k] = json.loads(d[k])
            except ValueError:
                pass
    return d


def rows(conn, sql, params=()):
    return [row_to_dict(r) for r in conn.execute(sql, params).fetchall()]


def one(conn, sql, params=()):
    return row_to_dict(conn.execute(sql, params).fetchone())


def get_config(conn):
    cfg = dict(config.DEFAULT_CONFIG)
    for r in conn.execute("SELECT `key`, value FROM config").fetchall():
        cfg[r["key"]] = json.loads(r["value"])
    return cfg


def set_config(conn, key, value):
    conn.execute(
        "INSERT INTO config(`key`, value) VALUES(%s, %s) "
        "ON DUPLICATE KEY UPDATE value = %s",
        (key, json.dumps(value, ensure_ascii=False), json.dumps(value, ensure_ascii=False)),
    )


def current_batch(conn):
    r = conn.execute("SELECT value FROM config WHERE `key` = 'current_batch'").fetchone()
    return json.loads(r["value"]) if r else -1


def has_schema(conn):
    r = conn.execute(
        "SELECT TABLE_NAME FROM information_schema.tables WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='content'"
    ).fetchone()
    return r is not None
