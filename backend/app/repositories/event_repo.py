"""事件、改级记录、处置记录、话术草案的数据访问。"""
from ..core.config import TERMINAL_STATUSES
from ..db.session import one, rows


def get(conn, eid: str):
    return one(conn, "SELECT * FROM event WHERE id = %s", (eid,))


def list_events(conn, level: str | None = None, status: str | None = None) -> list[dict]:
    where, params = [], []
    if level:
        where.append("level = %s")
        params.append(level)
    if status:
        where.append("status = %s")
        params.append(status)
    sql = "SELECT * FROM event " + ("WHERE " + " AND ".join(where) if where else "") + \
          " ORDER BY intensity_score DESC, id"
    return rows(conn, sql, params)


def list_brief(conn) -> list[dict]:
    return rows(conn, "SELECT id, title, level, intensity_score, status, manual_override "
                      "FROM event ORDER BY intensity_score DESC, id")


def count_active(conn) -> int:
    marks = ",".join(["%s"] * len(TERMINAL_STATUSES))
    return conn.execute(f"SELECT COUNT(*) FROM event WHERE status NOT IN ({marks})",
                        tuple(TERMINAL_STATUSES)).fetchone()[0]


def exists_for_topic(conn, tid: int) -> bool:
    return conn.execute("SELECT 1 FROM event WHERE topic_id = %s LIMIT 1", (tid,)).fetchone() is not None


# ---------- 人工改级 ----------

def set_manual_level(conn, eid: str, level: str, reason: str, operator: str, at: str) -> None:
    conn.execute("UPDATE event SET manual_override = 1, manual_level = %s, manual_reason = %s, "
                 "manual_by = %s, manual_at = %s, level = %s WHERE id = %s",
                 (level, reason, operator, at, level, eid))


def restore_auto_level(conn, eid: str, reason: str, operator: str, at: str) -> None:
    conn.execute("UPDATE event SET manual_override = 0, manual_level = NULL, manual_reason = %s, "
                 "manual_by = %s, manual_at = %s, level = auto_level WHERE id = %s",
                 (reason, operator, at, eid))


def add_level_adjustment(conn, eid, auto_level, auto_score, new_level, reason, operator, at) -> None:
    conn.execute("INSERT INTO level_adjustment(event_id, auto_level, auto_score, new_level, reason, "
                 "operator, created_at) VALUES(%s,%s,%s,%s,%s,%s,%s)",
                 (eid, auto_level, auto_score, new_level, reason, operator, at))


def level_adjustments(conn, eid: str) -> list[dict]:
    return rows(conn, "SELECT * FROM level_adjustment WHERE event_id = %s ORDER BY id DESC", (eid,))


# ---------- 处置 ----------

def set_status(conn, eid: str, status: str) -> None:
    conn.execute("UPDATE event SET status = %s WHERE id = %s", (status, eid))


def add_disposal(conn, eid, from_status, to_status, operator, role, note, at) -> None:
    conn.execute("INSERT INTO disposal_action(event_id, from_status, to_status, operator, role, note, "
                 "created_at) VALUES(%s,%s,%s,%s,%s,%s,%s)",
                 (eid, from_status, to_status, operator, role, note, at))


def disposals(conn, eid: str) -> list[dict]:
    return rows(conn, "SELECT * FROM disposal_action WHERE event_id = %s ORDER BY id", (eid,))


# ---------- 话术草案 ----------

def drafts(conn, eid: str) -> list[dict]:
    return rows(conn, "SELECT * FROM response_draft WHERE event_id = %s ORDER BY id DESC", (eid,))


def get_draft(conn, draft_id: int):
    return one(conn, "SELECT * FROM response_draft WHERE id = %s", (draft_id,))


def get_event_draft(conn, eid: str, draft_id: int | None):
    if draft_id:
        return one(conn, "SELECT * FROM response_draft WHERE id = %s AND event_id = %s", (draft_id, eid))
    return one(conn, "SELECT * FROM response_draft WHERE event_id = %s ORDER BY id DESC LIMIT 1", (eid,))


def add_draft(conn, eid, content, gen_mode, model_name, created_by, at) -> int:
    cur = conn.execute("INSERT INTO response_draft(event_id, content, gen_mode, model_name, created_by, "
                       "created_at) VALUES(%s,%s,%s,%s,%s,%s)",
                       (eid, content, gen_mode, model_name, created_by, at))
    return cur.lastrowid


def adopt_draft(conn, eid: str, draft_id: int, operator: str, at: str) -> None:
    conn.execute("UPDATE response_draft SET adopted = 0 WHERE event_id = %s", (eid,))
    conn.execute("UPDATE response_draft SET adopted = 1, adopted_by = %s, adopted_at = %s WHERE id = %s",
                 (operator, at, draft_id))
