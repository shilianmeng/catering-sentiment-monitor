"""事件专题：详情、溯源、人工改级、处置流转、话术草案。"""
from ..core.config import NEXT_STATUS, TERMINAL_STATUSES
from ..core.exceptions import BadRequest, NotFound
from ..db.session import current_batch, get_config, write_lock
from ..engine import agent, reporting, trace
from ..repositories import alert_repo, content_repo, event_repo
from ..utils import now_str

LEVELS = ("S", "A", "B", "C")


def get_or_404(conn, eid: str) -> dict:
    ev = event_repo.get(conn, eid)
    if not ev:
        raise NotFound(f"事件 {eid} 不存在")
    return ev


def volume_series(conn, eid: str) -> list[dict]:
    return reporting._volume_series(content_repo.event_sentiment_rows(conn, eid), current_batch(conn))


def list_events(conn, level: str | None, status: str | None) -> list[dict]:
    evs = event_repo.list_events(conn, level, status)
    for ev in evs:
        ev["content_count"], ev["negative_count"] = content_repo.event_counts(conn, ev["id"])
    return evs


def detail(conn, eid: str) -> dict:
    ev = get_or_404(conn, eid)
    ev["content_count"], ev["negative_count"] = content_repo.event_counts(conn, eid)
    ev["merged_count"] = content_repo.event_merged_count(conn, eid)
    ev["clusters"] = agent.clusters_with_quotes(conn, eid)
    ev["level_adjustments"] = event_repo.level_adjustments(conn, eid)
    ev["next_statuses"] = NEXT_STATUS.get(ev["status"], [])
    ev["drafts"] = event_repo.drafts(conn, eid)
    ev["alerts"] = alert_repo.list_alerts(conn, event_id=eid)
    ev["series"] = volume_series(conn, eid)
    ev["llm_available"] = agent.llm_available()
    return ev


def timeline(conn, eid: str) -> list[dict]:
    get_or_404(conn, eid)
    return trace.timeline(conn, eid)


def graph(conn, eid: str) -> dict:
    get_or_404(conn, eid)
    return trace.graph(conn, eid)


def change_level(conn, eid: str, level: str, reason: str, user: dict) -> dict:
    level, reason = level.strip(), reason.strip()
    if level not in (*LEVELS, "auto"):
        raise BadRequest("等级只能是 S / A / B / C，或 auto（恢复自动评级）")
    if not reason:
        raise BadRequest("人工改级必须填写理由")
    with write_lock:
        ev = get_or_404(conn, eid)
        t, operator = now_str(), user["display_name"]
        if level == "auto":
            event_repo.restore_auto_level(conn, eid, reason, operator, t)
            recorded = f"恢复自动({ev['auto_level']})"
        else:
            event_repo.set_manual_level(conn, eid, level, reason, operator, t)
            recorded = level
        event_repo.add_level_adjustment(conn, eid, ev["auto_level"], ev["auto_score"], recorded, reason, operator, t)
        conn.commit()
    return get_or_404(conn, eid)


def dispose(conn, eid: str, to_status: str, note: str, user: dict) -> dict:
    to_status, note = to_status.strip(), note.strip()
    with write_lock:
        cur = get_or_404(conn, eid)["status"]
        if cur in TERMINAL_STATUSES:
            raise BadRequest(f"事件已是「{cur}」，处置流程已结束，不能再流转")
        allowed = NEXT_STATUS.get(cur, [])
        if to_status not in allowed:
            raise BadRequest(f"不允许从「{cur}」直接流转到「{to_status}」，只能流转到：{'、'.join(allowed)}")
        event_repo.set_status(conn, eid, to_status)
        event_repo.add_disposal(conn, eid, cur, to_status, user["display_name"], user["role"], note, now_str())
        conn.commit()
    return {"status": to_status, "next_statuses": NEXT_STATUS.get(to_status, []),
            "disposals": event_repo.disposals(conn, eid)}


def disposals(conn, eid: str) -> list[dict]:
    get_or_404(conn, eid)
    return event_repo.disposals(conn, eid)


def generate_draft(conn, eid: str, user: dict) -> dict:
    get_or_404(conn, eid)
    text, gen_mode, model = agent.generate_draft(conn, eid, get_config(conn))   # 可能调大模型，放在锁外
    with write_lock:
        did = event_repo.add_draft(conn, eid, text, gen_mode, model, user["display_name"], now_str())
        conn.commit()
    return event_repo.get_draft(conn, did)


def adopt_draft(conn, eid: str, draft_id: int | None, user: dict) -> dict:
    get_or_404(conn, eid)
    d = event_repo.get_event_draft(conn, eid, draft_id)
    if not d:
        raise BadRequest("还没有话术草案，请先生成")
    with write_lock:
        event_repo.adopt_draft(conn, eid, d["id"], user["display_name"], now_str())
        conn.commit()
    return event_repo.get_draft(conn, d["id"])
