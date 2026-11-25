"""预警查询与已读标记。"""
from ..core.exceptions import NotFound
from ..db.session import write_lock
from ..repositories import alert_repo


def list_alerts(conn, event_id: str | None) -> list[dict]:
    return alert_repo.list_alerts(conn, event_id=event_id)


def mark_read(conn, aid: int) -> None:
    with write_lock:
        n = alert_repo.mark_alert_read(conn, aid)
        conn.commit()
    if not n:
        raise NotFound("预警不存在")
