"""监测主题（= 一个客户总部）CRUD。

一条主题带一份品牌画像：品牌名、别名（关键词）、门店/产品实体、事件议题规则。
新建时只填名称和关键词也能用：品牌取第一个关键词，议题规则留空则由引擎走餐饮行业默认规则。
"""
from ..core.config import SOURCE_TYPES
from ..core.exceptions import BadRequest, Conflict, NotFound
from ..db.session import write_lock
from ..repositories import content_repo, event_repo, topic_repo


def _split_keywords(kws) -> list[str]:
    if isinstance(kws, str):
        kws = kws.replace("，", ",").split(",")
    return [str(k).strip() for k in (kws or []) if str(k).strip()]


def _clean(data: dict) -> tuple[str, list[str], dict, int, str, list, list]:
    name = str(data.get("name") or "").strip()
    kws = _split_keywords(data.get("keywords"))
    if not name:
        raise BadRequest("主题名称不能为空")
    if not kws:
        raise BadRequest("至少填写一个关键词")
    ch = data.get("channels") or {}
    channels = {s: bool(ch.get(s, True)) for s in SOURCE_TYPES}   # 未指定的渠道默认开启
    brand = str(data.get("brand") or kws[0]).strip() or kws[0]
    entities = data.get("entities") or []
    event_rules = data.get("event_rules") or []
    if not isinstance(entities, list) or not isinstance(event_rules, list):
        raise BadRequest("entities / event_rules 必须是数组")
    return name, kws, channels, 1 if data.get("enabled", True) else 0, brand, entities, event_rules


def _get_or_404(conn, tid: int) -> dict:
    t = topic_repo.get_topic(conn, tid)
    if not t:
        raise NotFound("主题不存在")
    return t


def list_topics(conn) -> list[dict]:
    ts = topic_repo.list_topics(conn)
    for t in ts:
        t["content_count"] = content_repo.count_by_topic(conn, t["id"])
    return ts


def create(conn, data: dict, user: dict) -> dict:
    name, kws, channels, enabled, brand, entities, rules = _clean(data)
    with write_lock:
        tid = topic_repo.insert_topic(conn, name, kws, channels, brand, entities, rules,
                                      user["username"], enabled)
        conn.commit()
    return topic_repo.get_topic(conn, tid)


def update(conn, tid: int, changes: dict) -> dict:
    """部分更新：只覆盖传了的字段；channels 与原值合并。"""
    old = _get_or_404(conn, tid)
    merged = {**old, **changes}
    if "channels" in changes:
        merged["channels"] = {**(old.get("channels") or {}), **(changes["channels"] or {})}
    name, kws, channels, enabled, brand, entities, rules = _clean(merged)
    with write_lock:
        topic_repo.update_topic(conn, tid, name, kws, channels, brand, entities, rules, enabled)
        conn.commit()
    return topic_repo.get_topic(conn, tid)


def delete(conn, tid: int) -> None:
    _get_or_404(conn, tid)
    with write_lock:
        if topic_repo.content_exists_for_topic(conn, tid) or event_repo.exists_for_topic(conn, tid):
            raise Conflict("主题已关联内容或事件，不能删除；可停用该主题")
        if topic_repo.official_or_store_exists_for_topic(conn, tid):
            raise Conflict("主题下还有门店或官方处罚记录，不能删除；可停用该主题")
        topic_repo.delete_topic(conn, tid)
        conn.commit()
