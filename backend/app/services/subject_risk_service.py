"""主体风险：从库里取带企业全名的官方处罚记录，交给 engine.subject_risk 归并、打分、画像。只读，不落库。

违法行为类型（cfWfxw）库里没有单独的列，从入库时存下的详情快照里读；快照缺失就只按处罚机关和案情分类。
处理结果和罚款金额也按当前规则从快照重新解析（v2 起认大写金额）；库里的值由 `python -m app.collectors
--source yx_sgs --reparse` 回写（2026-11-23 已回写 v2），这里再解析一遍是为了规则升级后不用先回写也能看到新结果。
"""
from ..collectors import snapshot, yuexiu_sgs
from ..core.exceptions import BadRequest, NotFound
from ..db.session import rows
from ..engine import subject_report, subject_risk
from .store_risk_service import _as_of

# 当事人带全名的来源；gkmlpt 典型案例是脱敏的（某餐厅），不参与主体排名
NAMED_SOURCES = {yuexiu_sgs.SOURCE_ID}
_COLS = ("id, source_id, subject, article_title, doc_no, official_url, published_at, enforcement_dept, "
         "violation, regulation_text, investigation_status, handling_result, fine_amount, snapshot_sha256")


def _source(source_id: str | None) -> str:
    sid = source_id or yuexiu_sgs.SOURCE_ID
    if sid not in NAMED_SOURCES:
        raise BadRequest(f"来源 {sid} 的当事人是脱敏的，不能按主体评分；可选：{', '.join(sorted(NAMED_SOURCES))}")
    return sid


def _category(value: str | None) -> str | None:
    if value and value not in subject_risk.CATEGORIES:
        raise BadRequest(f"category 只能是：{'、'.join(subject_risk.CATEGORIES)}")
    return value or None


def _from_snapshot(sha: str | None, snapshot_root=None) -> dict | None:
    """按当前解析规则从详情快照重新解析（只在内存里，不回写库）。库里的记录可能是旧版规则解析的。"""
    if not sha:
        return None
    body = snapshot.load(sha, snapshot_root)
    if body is None:
        return None
    try:
        info = yuexiu_sgs.parse_detail(body)
    except ValueError:
        return None
    result, fine = yuexiu_sgs.handling_result(info.get("cfCflb"), info.get("cfNr"))
    return {"violation_type": info.get("cfWfxw") or None, "handling_result": result, "fine_amount": fine}


def load_records(conn, source_id: str | None = None, snapshot_root=None) -> list[dict]:
    sid = _source(source_id)
    recs = rows(conn, f"SELECT {_COLS} FROM official_record WHERE source_id = %s AND is_catering = 1", (sid,))
    for r in recs:
        live = _from_snapshot(r.pop("snapshot_sha256"), snapshot_root)
        r["violation_type"] = None
        r["reparsed"] = False
        if live:
            r["reparsed"] = (live["handling_result"], live["fine_amount"]) != (r["handling_result"], r["fine_amount"])
            r.update(live)
        k = subject_risk.subject_key(r)
        r["credit_code"] = None if k.startswith("name:") else k
    return recs


def ranking(conn, source_id=None, as_of=None, category=None, level=None, limit: int | None = 50,
            snapshot_root=None) -> dict:
    ref, cat = _as_of(as_of), _category(category)
    ranked = subject_risk.rank(load_records(conn, source_id, snapshot_root), ref, cat)
    if level:
        ranked = [s for s in ranked if s["level"] == level]
    total = len(ranked)
    if limit:
        ranked = ranked[:limit]
    for s in ranked:                       # 排名列表不带逐条明细，明细走单主体接口
        s["records"] = [{k: x[k] for k in ("id", "doc_no", "tier", "points", "category", "official_url")}
                        for x in s["records"]]
    return {"source_id": _source(source_id), "as_of": str(ref), "category": cat, "total": total,
            "subjects": ranked}


def subject_detail(conn, key: str, source_id=None, as_of=None, snapshot_root=None) -> dict:
    ref = _as_of(as_of)
    recs = [r for r in load_records(conn, source_id, snapshot_root) if subject_risk.subject_key(r) == key]
    if not recs:
        raise NotFound("主体不存在")
    return {"source_id": _source(source_id), "as_of": str(ref), **subject_risk.score_subject(recs, ref)}


CHAIN_EXAMPLE = "百胜餐饮"     # 越秀数据里唯一有多家门店被罚的连锁（肯德基 / 必胜客，各店独立登记、信用代码不同）


def health_report(conn, key: str, source_id=None, as_of=None, snapshot_root=None) -> dict:
    """第④步：单主体体检报告。排名、评分和 /subjects/risk 同一批数据、同一套规则。"""
    ref = _as_of(as_of)
    sid = _source(source_id)
    recs = load_records(conn, sid, snapshot_root)
    mine = [r for r in recs if subject_risk.subject_key(r) == key]
    if not mine:
        raise NotFound("主体不存在")
    ranked = subject_risk.rank(recs, ref)
    food = subject_risk.rank(recs, ref, subject_risk.CAT_FOOD)
    district = {"as_of": str(ref), "total": len(ranked),
                "rank": next(s["rank"] for s in ranked if s["subject_key"] == key),
                "category_total": len(food),
                "category_rank": next((s["rank"] for s in food if s["subject_key"] == key), None)}
    chain = [r for r in recs if CHAIN_EXAMPLE in (r.get("subject") or "") and subject_risk.subject_key(r) != key]
    return subject_report.build(subject_risk.score_subject(mine, ref), mine, district, chain)


def export_report(conn, key: str, fmt: str = "md", source_id=None, as_of=None,
                  snapshot_root=None) -> tuple[bytes, str, str]:
    if fmt not in ("md", "pdf"):
        raise BadRequest("format 只能是 md 或 pdf")
    rep = health_report(conn, key, source_id, as_of, snapshot_root)
    name = f"{rep['title']}_{rep['as_of']}"
    if fmt == "md":
        return subject_report.to_markdown(rep).encode("utf-8"), "text/markdown; charset=utf-8", f"{name}.md"
    return subject_report.to_pdf(rep), "application/pdf", f"{name}.pdf"


def district_profile(conn, source_id=None, as_of=None, top: int = 10, snapshot_root=None) -> dict:
    ref = _as_of(as_of)
    sid = _source(source_id)
    recs = load_records(conn, sid, snapshot_root)
    # 数据截止日（最近一条处罚的公示日期）和评估日期 as_of 是两回事，页面要分开标
    data_until = max((r["published_at"] for r in recs if r.get("published_at")), default=None)
    return {"source_id": sid, "data_until": data_until, **subject_risk.profile(recs, ref, top)}
