"""内容表数据访问。"""
from ..db.session import one, rows

_FILTER_COLUMNS = {
    "topic_id": "c.topic_id", "source_type": "c.source_type", "sentiment": "c.sentiment",
    "level": "e.level", "emotion": "c.emotion", "event_id": "c.event_id", "media_type": "c.media_type",
    "source_category": "c.source_category", "store_id": "c.store_id",
}


def search(conn, filters: dict, include_dup: bool, page: int, page_size: int) -> tuple[int, list[dict]]:
    where, params = [], []
    if not include_dup:
        where.append("c.dup_of IS NULL")
    for key, col in _FILTER_COLUMNS.items():
        val = filters.get(key)
        if val not in (None, ""):
            where.append(f"{col} = %s")
            params.append(val)
    if filters.get("start"):
        where.append("c.published_at >= %s")
        params.append(filters["start"].replace("T", " ")[:16])
    if filters.get("end"):
        where.append("c.published_at <= %s")
        params.append(filters["end"].replace("T", " ")[:16])
    if filters.get("keyword"):
        where.append("(c.text LIKE %s OR c.ocr_text LIKE %s OR c.asr_text LIKE %s OR c.author LIKE %s)")
        params += [f"%{filters['keyword']}%"] * 4
    sql_where = ("WHERE " + " AND ".join(where)) if where else ""
    base = f"FROM content c LEFT JOIN event e ON e.id = c.event_id {sql_where}"
    total = conn.execute(f"SELECT COUNT(*) {base}", params).fetchone()[0]
    items = rows(conn, f"SELECT c.*, e.level AS event_level, e.title AS event_title {base} "
                       f"ORDER BY c.published_at DESC, c.id DESC LIMIT %s OFFSET %s",
                 params + [page_size, (page - 1) * page_size])
    return total, items


def get_with_event(conn, cid: str):
    return one(conn, "SELECT c.*, e.level AS event_level, e.title AS event_title FROM content c "
                     "LEFT JOIN event e ON e.id = c.event_id WHERE c.id = %s", (cid,))


def get_brief(conn, cid: str):
    return one(conn, "SELECT id, author, platform, published_at, text, parent_id FROM content WHERE id = %s", (cid,))


def merged_items(conn, cid: str) -> list[dict]:
    return rows(conn, "SELECT id, author, platform, published_at, text FROM content "
                      "WHERE dup_of = %s ORDER BY id", (cid,))


def list_for_overview(conn) -> list[dict]:
    return rows(conn, "SELECT id, batch_no, sentiment, text, ocr_text, asr_text FROM content "
                      "WHERE dup_of IS NULL ORDER BY published_at, id")


def count_merged(conn) -> int:
    return conn.execute("SELECT COUNT(*) FROM content WHERE dup_of IS NOT NULL").fetchone()[0]


def event_counts(conn, eid: str) -> tuple[int, int]:
    """返回（去重后内容数, 其中负向数）。"""
    r = conn.execute("SELECT COUNT(*) n, SUM(sentiment='负向') neg FROM content "
                     "WHERE event_id = %s AND dup_of IS NULL", (eid,)).fetchone()
    return r["n"], int(r["neg"] or 0)


def event_merged_count(conn, eid: str) -> int:
    return conn.execute("SELECT COUNT(*) FROM content WHERE event_id = %s AND dup_of IS NOT NULL",
                        (eid,)).fetchone()[0]


def event_sentiment_rows(conn, eid: str) -> list[dict]:
    return rows(conn, "SELECT batch_no, sentiment FROM content WHERE event_id = %s AND dup_of IS NULL", (eid,))


def count_by_topic(conn, tid: int) -> int:
    return conn.execute("SELECT COUNT(*) FROM content WHERE topic_id = %s AND dup_of IS NULL",
                        (tid,)).fetchone()[0]


def count_by_store(conn, store_id: int) -> int:
    return conn.execute("SELECT COUNT(*) FROM content WHERE store_id = %s AND dup_of IS NULL",
                        (store_id,)).fetchone()[0]
