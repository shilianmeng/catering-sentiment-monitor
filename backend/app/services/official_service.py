"""官方处罚记录：查询、来源状态、手动触发采集。"""
from ..collectors import pipeline, snapshot
from ..core.config import OFFICIAL_SOURCES
from ..core.exceptions import BadRequest, NotFound
from ..db.session import one, rows, write_lock

_FILTERS = {"source_id": "source_id", "investigation_status": "investigation_status",
            "topic_id": "topic_id", "store_id": "store_id"}


def search(conn, filters: dict, page: int, page_size: int) -> dict:
    where, params = [], []
    for key, col in _FILTERS.items():
        if filters.get(key) not in (None, ""):
            where.append(f"{col} = %s")
            params.append(filters[key])
    if filters.get("catering") is not None:
        where.append("is_catering = %s")
        params.append(1 if filters["catering"] else 0)
    if filters.get("keyword"):
        where.append("(subject LIKE %s OR case_title LIKE %s OR violation LIKE %s)")
        params += [f"%{filters['keyword']}%"] * 3
    sql_where = ("WHERE " + " AND ".join(where)) if where else ""
    total = conn.execute(f"SELECT COUNT(*) FROM official_record {sql_where}", params).fetchone()[0]
    page, page_size = max(1, page), min(max(1, page_size), 100)
    items = rows(conn, f"SELECT id, source_id, source_name, official_url, article_title, doc_no, case_no, "
                       f"case_title, subject, enforcement_dept, region, published_at, decided_at, "
                       f"investigation_status, handling_result, fine_amount, is_catering, topic_id, store_id, "
                       f"revision FROM official_record {sql_where} "
                       f"ORDER BY published_at DESC, source_id, case_no LIMIT %s OFFSET %s",
                 params + [page_size, (page - 1) * page_size])
    return {"total": total, "page": page, "page_size": page_size, "items": items}


def detail(conn, rid: int) -> dict:
    r = one(conn, "SELECT * FROM official_record WHERE id = %s", (rid,))
    if not r:
        raise NotFound("官方记录不存在")
    snap = one(conn, "SELECT sha256, url, bytes, fetched_at FROM source_snapshot WHERE sha256 = %s",
               (r["snapshot_sha256"],)) if r.get("snapshot_sha256") else None
    if snap:
        snap["available"] = snapshot.load(snap["sha256"]) is not None   # 本机快照文件还在且没被改
    r["snapshot"] = snap
    return r


def sources_status(conn) -> list[dict]:
    out = []
    for s in OFFICIAL_SOURCES:
        stat = one(conn, "SELECT COUNT(*) n, SUM(is_catering) catering, MAX(fetched_at) last_fetched, "
                         "MAX(published_at) latest FROM official_record WHERE source_id = %s", (s["id"],))
        out.append({"id": s["id"], "name": s["name"], "region": s["region"], "base_url": s["base_url"],
                    "records": stat["n"], "catering": int(stat["catering"] or 0),
                    "last_fetched": stat["last_fetched"], "latest_published": stat["latest"]})
    return out


def collect(conn, source_id: str, pages: int) -> dict:
    if source_id not in {s["id"] for s in OFFICIAL_SOURCES}:
        raise BadRequest("未知采集源")
    with write_lock:
        return pipeline.collect(conn, source_id, max_pages=pages)
