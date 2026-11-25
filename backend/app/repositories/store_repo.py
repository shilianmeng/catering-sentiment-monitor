"""门店表数据访问。"""
import json

from ..db.session import one, rows

_COLS = ("topic_id", "name", "aliases", "ownership", "province", "city", "district", "address",
         "license_subject", "status")


def list_stores(conn, topic_id: int | None = None) -> list[dict]:
    if topic_id is None:
        return rows(conn, "SELECT * FROM store ORDER BY topic_id, id")
    return rows(conn, "SELECT * FROM store WHERE topic_id = %s ORDER BY id", (topic_id,))


def get_store(conn, sid: int):
    return one(conn, "SELECT * FROM store WHERE id = %s", (sid,))


def find_by_name(conn, topic_id: int, name: str):
    return one(conn, "SELECT * FROM store WHERE topic_id = %s AND name = %s", (topic_id, name))


def _values(data: dict) -> list:
    return [json.dumps(data.get(c) or [], ensure_ascii=False) if c == "aliases" else data.get(c) for c in _COLS]


def insert_store(conn, data: dict) -> int:
    cur = conn.execute(f"INSERT INTO store({', '.join(_COLS)}) VALUES({', '.join(['%s'] * len(_COLS))})",
                       _values(data))
    return cur.lastrowid


def update_store(conn, sid: int, data: dict) -> None:
    cols = [c for c in _COLS if c != "topic_id"]
    conn.execute(f"UPDATE store SET {', '.join(f'{c} = %s' for c in cols)} WHERE id = %s",
                 [v for c, v in zip(_COLS, _values(data)) if c != "topic_id"] + [sid])


def delete_store(conn, sid: int) -> None:
    conn.execute("DELETE FROM store WHERE id = %s", (sid,))


def referenced(conn, sid: int) -> bool:
    for table in ("content", "official_record"):
        if conn.execute(f"SELECT 1 FROM {table} WHERE store_id = %s LIMIT 1", (sid,)).fetchone():
            return True
    return False
