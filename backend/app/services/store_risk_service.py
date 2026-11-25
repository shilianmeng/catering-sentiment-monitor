"""门店风险：从库里取门店、挂到门店的官方记录和内容，交给 engine.store_risk 算分。只读，不落库。"""
from datetime import date

from ..core.exceptions import BadRequest, NotFound
from ..db.session import rows
from ..engine import store_risk
from ..repositories import store_repo, topic_repo

_OFFICIAL_COLS = ("id, subject, case_title, official_url, published_at, investigation_status, handling_result, "
                  "fine_amount, topic_id, store_id")
_CONTENT_COLS = "id, store_id, topic_id, source_category, sentiment, dup_of, published_at"


def _as_of(value: str | None) -> date:
    if not value:
        return date.today()
    d = store_risk._to_date(value)
    if d is None or len(value) < 10:
        raise BadRequest("as_of 要写成 YYYY-MM-DD")
    return d


def _by_store(items: list[dict]) -> dict:
    out = {}
    for it in items:
        out.setdefault(it["store_id"], []).append(it)
    return out


def topic_risk(conn, topic_id: int, as_of: str | None = None) -> dict:
    topic = topic_repo.get_topic(conn, topic_id)
    if not topic:
        raise NotFound("主题不存在")
    ref = _as_of(as_of)
    stores = store_repo.list_stores(conn, topic_id)
    officials = rows(conn, f"SELECT {_OFFICIAL_COLS} FROM official_record WHERE topic_id = %s", (topic_id,))
    contents = rows(conn, f"SELECT {_CONTENT_COLS} FROM content WHERE topic_id = %s", (topic_id,))
    store_ids = {s["id"] for s in stores}
    off_by, con_by = _by_store(officials), _by_store(contents)
    scores = [store_risk.score_store(s, off_by.get(s["id"], []), con_by.get(s["id"], []), ref) for s in stores]
    unlinked = [r for r in officials if r["store_id"] not in store_ids]
    unattributed = sum(1 for c in contents if c["store_id"] not in store_ids and store_risk.is_complaint(c))
    summary = store_risk.brand_summary(stores, scores, unlinked, unattributed, ref)
    return {"topic_id": topic_id, "brand": topic.get("brand") or topic["name"], **summary}


def all_topics_risk(conn, as_of: str | None = None) -> list[dict]:
    return [topic_risk(conn, t["id"], as_of) for t in topic_repo.list_topics(conn)]


def store_risk_detail(conn, sid: int, as_of: str | None = None) -> dict:
    store = store_repo.get_store(conn, sid)
    if not store:
        raise NotFound("门店不存在")
    ref = _as_of(as_of)
    officials = rows(conn, f"SELECT {_OFFICIAL_COLS} FROM official_record WHERE store_id = %s", (sid,))
    contents = rows(conn, f"SELECT {_CONTENT_COLS} FROM content WHERE store_id = %s", (sid,))
    return {"as_of": str(ref), **store_risk.score_store(store, officials, contents, ref)}
