"""报告中心：生成、查询、导出 Markdown / PDF。"""
from ..core.exceptions import BadRequest, BizError, NotFound
from ..db.session import get_config, write_lock
from ..engine import reporting
from ..repositories import report_repo
from ..utils import now_str
from . import event_service

EXPORT_FORMATS = ("md", "pdf")


def get(conn, rid: int) -> dict:
    r = report_repo.get_report(conn, rid)
    if not r:
        raise NotFound(f"报告 {rid} 不存在")
    r["markdown"] = reporting.to_markdown(r)
    return r


def create(conn, eid: str, user: dict) -> dict:
    event_service.get_or_404(conn, eid)
    rep = reporting.build_report(conn, eid, get_config(conn))     # 可能调大模型，放在锁外
    with write_lock:
        rid = report_repo.insert_report(conn, eid, rep, user["display_name"], now_str())
        conn.commit()
    return get(conn, rid)


def list_reports(conn) -> list[dict]:
    return report_repo.list_reports(conn)


def export(conn, rid: int, fmt: str) -> tuple[bytes, str, str]:
    """返回（文件内容, MIME 类型, 文件名）。"""
    if fmt not in EXPORT_FORMATS:
        raise BadRequest("format 只能是 md 或 pdf")
    r = get(conn, rid)
    fname = f"report_{rid}_{r['event_id']}"
    if fmt == "md":
        return r["markdown"].encode("utf-8"), "text/markdown; charset=utf-8", f"{fname}.md"
    try:
        data = reporting.to_pdf(r, event_service.volume_series(conn, r["event_id"]))
    except RuntimeError as e:          # 本机缺中文字体等
        raise BizError(str(e), 500)
    return data, "application/pdf", f"{fname}.pdf"
