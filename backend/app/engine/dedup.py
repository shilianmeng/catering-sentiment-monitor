"""去重聚合模块：64 位 SimHash 判重 + 按「客户画像」把内容聚合到事件。

品牌、别名、门店、议题规则全部来自 topic 表（一个客户总部一条），
代码里不出现任何具体品牌名：换客户是改数据，不是改代码。
"""
import hashlib
import json

from . import profile
from .tagging import clean_text

HAMMING_LIMIT = 3


def _hash64(token):
    return int.from_bytes(hashlib.md5(token.encode("utf-8")).digest()[:8], "big")


def simhash(text):
    """字符 bigram 加权的 64 位 SimHash，返回 16 位十六进制字符串。"""
    s = clean_text(text)
    grams = [s[i:i + 2] for i in range(len(s) - 1)] or ([s] if s else [])
    v = [0] * 64
    for g in grams:
        h = _hash64(g)
        for i in range(64):
            v[i] += 1 if (h >> i) & 1 else -1
    fp = 0
    for i in range(64):
        if v[i] > 0:
            fp |= 1 << i
    return f"{fp:016x}"


def hamming(a, b):
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def find_duplicate(conn, fp):
    """在已入库的非重复内容里找海明距离 ≤3 的首发，返回其 id。"""
    for r in conn.execute(
        "SELECT id, simhash FROM content WHERE dup_of IS NULL AND simhash IS NOT NULL "
        "ORDER BY published_at, id"
    ):
        if hamming(fp, r["simhash"]) <= HAMMING_LIMIT:
            return r["id"]
    return None


def assign_event(conn, item, text, topic, now):
    """返回内容所属事件 id；转发/引用跟随被转内容的事件，否则按议题归类。

    提到了品牌但不符合任何议题的内容不硬塞进别的事件，返回 None（仍会入库、进大盘）。
    """
    if item.get("parent_id"):
        r = conn.execute("SELECT event_id FROM content WHERE id = %s", (item["parent_id"],)).fetchone()
        if r and r["event_id"]:
            return r["event_id"]
    rule = profile.match_rule(topic, text)
    if rule is None:
        return None
    r = conn.execute("SELECT id FROM event WHERE topic_id = %s AND category = %s",
                     (topic["id"], rule["category"])).fetchone()
    if r:
        return r["id"]
    n = conn.execute("SELECT COUNT(*) FROM event").fetchone()[0] + 1
    eid = f"ev{n:03d}"
    conn.execute(
        "INSERT INTO event(id, topic_id, category, title, keywords, first_content_id, created_at) "
        "VALUES(%s, %s, %s, %s, %s, %s, %s)",
        (eid, topic["id"], rule["category"], profile.render_title(topic, rule),
         json.dumps(rule.get("keywords") or [], ensure_ascii=False), item["id"], now),
    )
    return eid
