"""监测主题（= 一个客户总部）表数据访问。"""
import json

from ..db.session import one, rows


def list_topics(conn) -> list[dict]:
    return rows(conn, "SELECT * FROM topic ORDER BY id")


def get_topic(conn, tid: int):
    return one(conn, "SELECT * FROM topic WHERE id = %s", (tid,))


def insert_topic(conn, name, keywords, channels, brand, entities, event_rules, created_by, enabled) -> int:
    cur = conn.execute(
        "INSERT INTO topic(name, keywords, channels, brand, entities, event_rules, created_by, enabled) "
        "VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
        (name, json.dumps(keywords, ensure_ascii=False), json.dumps(channels, ensure_ascii=False),
         brand, json.dumps(entities or [], ensure_ascii=False),
         json.dumps(event_rules or [], ensure_ascii=False), created_by, enabled))
    return cur.lastrowid


def update_topic(conn, tid, name, keywords, channels, brand, entities, event_rules, enabled) -> None:
    conn.execute(
        "UPDATE topic SET name = %s, keywords = %s, channels = %s, brand = %s, entities = %s, "
        "event_rules = %s, enabled = %s WHERE id = %s",
        (name, json.dumps(keywords, ensure_ascii=False), json.dumps(channels, ensure_ascii=False),
         brand, json.dumps(entities or [], ensure_ascii=False),
         json.dumps(event_rules or [], ensure_ascii=False), enabled, tid))


def delete_topic(conn, tid: int) -> None:
    conn.execute("DELETE FROM topic WHERE id = %s", (tid,))


def content_exists_for_topic(conn, tid: int) -> bool:
    return conn.execute("SELECT 1 FROM content WHERE topic_id = %s LIMIT 1", (tid,)).fetchone() is not None


def official_or_store_exists_for_topic(conn, tid: int) -> bool:
    """门店和官方处罚记录都挂在品牌下，删品牌会留下指向不存在主题的记录。"""
    return (conn.execute("SELECT 1 FROM store WHERE topic_id = %s LIMIT 1", (tid,)).fetchone() is not None
            or conn.execute("SELECT 1 FROM official_record WHERE topic_id = %s LIMIT 1", (tid,)).fetchone()
            is not None)
