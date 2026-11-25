"""预警表数据访问。"""
from ..db.session import one, rows


def list_alerts(conn, event_id: str | None = None, limit: int | None = None) -> list[dict]:
    sql, params = "SELECT * FROM alert", []
    if event_id:
        sql += " WHERE event_id = %s"
        params.append(event_id)
    sql += " ORDER BY id DESC"
    if limit:
        sql += " LIMIT %s"
        params.append(limit)
    return rows(conn, sql, params)


def get_alert(conn, aid: int):
    return one(conn, "SELECT * FROM alert WHERE id = %s", (aid,))


def mark_alert_read(conn, aid: int) -> int:
    return conn.execute("UPDATE alert SET is_read = 1 WHERE id = %s", (aid,)).rowcount


def count_alerts(conn) -> tuple[int, int]:
    """返回（有效预警数, 其中未读数），被静默期抑制的不算。"""
    total = conn.execute("SELECT COUNT(*) FROM alert WHERE suppressed = 0").fetchone()[0]
    unread = conn.execute("SELECT COUNT(*) FROM alert WHERE suppressed = 0 AND is_read = 0").fetchone()[0]
    return total, unread
