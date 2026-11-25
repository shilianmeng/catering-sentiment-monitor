"""门店：一个品牌（topic）下的门店清单，区分直营/加盟和所在区域。

风险要落到具体门店：内容入库时按门店名/别名归到门店，官方处罚记录也按当事人挂到门店。
"""
from ..core.config import STORE_OWNERSHIP
from ..core.exceptions import BadRequest, Conflict, NotFound
from ..db.session import write_lock
from ..repositories import content_repo, store_repo, topic_repo

STORE_STATUSES = ("营业", "停业整改", "已关店")


def _clean(data: dict) -> dict:
    name = str(data.get("name") or "").strip()
    if not name:
        raise BadRequest("门店名称不能为空")
    if data.get("ownership") not in STORE_OWNERSHIP:
        raise BadRequest(f"经营方式只能是：{' / '.join(STORE_OWNERSHIP)}")
    if data.get("status") not in STORE_STATUSES:
        raise BadRequest(f"门店状态只能是：{' / '.join(STORE_STATUSES)}")
    aliases = [str(a).strip() for a in (data.get("aliases") or []) if str(a).strip() and str(a).strip() != name]
    return {**data, "name": name, "aliases": list(dict.fromkeys(aliases))}


def _with_counts(conn, store: dict) -> dict:
    store["content_count"] = content_repo.count_by_store(conn, store["id"])
    store["official_count"] = conn.execute(
        "SELECT COUNT(*) FROM official_record WHERE store_id = %s", (store["id"],)).fetchone()[0]
    return store


def list_stores(conn, topic_id: int | None = None) -> list[dict]:
    return [_with_counts(conn, s) for s in store_repo.list_stores(conn, topic_id)]


def get(conn, sid: int) -> dict:
    s = store_repo.get_store(conn, sid)
    if not s:
        raise NotFound("门店不存在")
    return _with_counts(conn, s)


def create(conn, data: dict) -> dict:
    if not topic_repo.get_topic(conn, data.get("topic_id")):
        raise NotFound("主题不存在")
    data = _clean(data)
    with write_lock:
        if store_repo.find_by_name(conn, data["topic_id"], data["name"]):
            raise Conflict("该品牌下已有同名门店")
        sid = store_repo.insert_store(conn, data)
        conn.commit()
    return get(conn, sid)


def update(conn, sid: int, changes: dict) -> dict:
    old = store_repo.get_store(conn, sid)
    if not old:
        raise NotFound("门店不存在")
    data = _clean({**old, **{k: v for k, v in changes.items() if v is not None}})
    with write_lock:
        other = store_repo.find_by_name(conn, old["topic_id"], data["name"])
        if other and other["id"] != sid:
            raise Conflict("该品牌下已有同名门店")
        store_repo.update_store(conn, sid, data)
        conn.commit()
    return get(conn, sid)


def delete(conn, sid: int) -> None:
    if not store_repo.get_store(conn, sid):
        raise NotFound("门店不存在")
    with write_lock:
        if store_repo.referenced(conn, sid):
            raise Conflict("门店已关联内容或官方记录，不能删除；可把状态改成「已关店」")
        store_repo.delete_store(conn, sid)
        conn.commit()
