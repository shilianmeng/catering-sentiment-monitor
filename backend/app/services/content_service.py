"""研判工作台：内容检索与详情（传播链、合并的水军帖）。"""
from ..core.exceptions import NotFound
from ..repositories import content_repo


def search(conn, filters: dict, include_dup: bool, page: int, page_size: int) -> dict:
    page_size = max(1, min(100, page_size))
    page = max(1, page)
    total, items = content_repo.search(conn, filters, include_dup, page, page_size)
    return {"total": total, "page": page, "page_size": page_size, "items": items}


def detail(conn, cid: str) -> dict:
    c = content_repo.get_with_event(conn, cid)
    if not c:
        raise NotFound(f"内容 {cid} 不存在")
    chain, p, seen = [], c.get("parent_id"), set()
    while p and p not in seen:          # 沿 parent_id 往上追溯转发链，防环
        seen.add(p)
        r = content_repo.get_brief(conn, p)
        if not r:
            break
        chain.append(r)
        p = r["parent_id"]
    c["parent_chain"] = chain
    c["merged_items"] = content_repo.merged_items(conn, cid)
    c["interaction"] = c["reposts"] + c["comments"] + c["likes"]
    return c
