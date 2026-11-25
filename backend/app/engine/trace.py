"""溯源模块：传播时间线（首发 / 关键引爆节点 / 转发层级）和实体关系图谱。"""
from ..db.session import rows

KEY_NODE_WEIGHT = 9            # 账号权重 ≥9 视为 KOL 引爆
KEY_NODE_INTERACTION = 20_000  # 单条转评赞 ≥2 万视为互动拐点


def timeline(conn, event_id):
    contents = rows(conn, "SELECT * FROM content WHERE event_id = %s AND dup_of IS NULL "
                          "ORDER BY published_at, id", (event_id,))
    by_id = {c["id"]: c for c in contents}
    ev = conn.execute("SELECT first_content_id FROM event WHERE id = %s", (event_id,)).fetchone()
    first_id = ev["first_content_id"] if ev else None

    def depth(c):
        d, seen = 0, set()
        while c.get("parent_id") and c["parent_id"] in by_id and c["id"] not in seen:
            seen.add(c["id"])
            c = by_id[c["parent_id"]]
            d += 1
        return d

    nodes = []
    for c in contents:
        inter = c["reposts"] + c["comments"] + c["likes"]
        marks = []
        if c["id"] == first_id:
            marks.append("首发")
        if c["kol_weight"] >= KEY_NODE_WEIGHT:
            marks.append("KOL引爆")
        elif inter >= KEY_NODE_INTERACTION and c["id"] != first_id:
            marks.append("互动拐点")
        nodes.append({
            "id": c["id"], "published_at": c["published_at"], "author": c["author"],
            "author_type": c["author_type"], "kol_weight": c["kol_weight"],
            "source_type": c["source_type"], "platform": c["platform"],
            "media_type": c["media_type"], "text": c["text"], "parent_id": c["parent_id"],
            "depth": depth(c), "interaction": inter, "sentiment": c["sentiment"],
            "dup_count": c["dup_count"], "marks": marks,
        })
    return {"first_content_id": first_id, "nodes": nodes}


def graph(conn, event_id):
    """实体共现图：同一条内容里同时出现的两个实体连一条边，权重为共现次数。"""
    contents = rows(conn, "SELECT id, entities FROM content WHERE event_id = %s AND dup_of IS NULL "
                          "ORDER BY published_at, id", (event_id,))
    nodes, edges = {}, {}
    for c in contents:
        ents = c["entities"] or []
        for e in ents:
            n = nodes.setdefault(e["name"], {"id": e["name"], "type": e["type"], "count": 0,
                                             "content_ids": []})
            n["count"] += 1
            if len(n["content_ids"]) < 5:
                n["content_ids"].append(c["id"])
        names = sorted(e["name"] for e in ents)
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                key = (names[i], names[j])
                edges[key] = edges.get(key, 0) + 1
    return {
        "nodes": sorted(nodes.values(), key=lambda n: (-n["count"], n["id"])),
        "edges": [{"source": a, "target": b, "weight": w}
                  for (a, b), w in sorted(edges.items(), key=lambda kv: (-kv[1], kv[0]))],
    }
