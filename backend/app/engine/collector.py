"""采集模块：按批次读取预置的多源模拟数据，按监测主题词包和信源开关过滤后入库。

文本、图片（附 OCR 文本）、音视频（附 ASR 转录）都在 seed_data.json 里预置，
页面上统一标注「模拟数据」「OCR 转录（模拟）」「ASR 转录（模拟）」。

过滤与归类全部按「主题」走：一个客户总部 = 一条 topic，品牌和议题规则在 topic 表里。
入库时同时判定来源类别（官方/媒体/投诉/品牌回应）和落在哪家门店（store 表）。
真实官方处罚走另一条线：app/collectors（抓取 → 快照 → official_record）。
"""
import json

from . import dedup, sources, tagging
from ..core.config import SEED_FILE

_seed_cache = None


def load_seed():
    global _seed_cache
    if _seed_cache is None:
        with open(SEED_FILE, encoding="utf-8") as f:
            _seed_cache = json.load(f)["contents"]
    return _seed_cache


def batch_items(batch_no):
    items = [c for c in load_seed() if c["batch_no"] == batch_no]
    return sorted(items, key=lambda c: (c["published_at"], c["id"]))


def match_topic(topics, item, text):
    """返回第一个命中的主题：关键词命中，且该主题打开了这条内容的信源通道。"""
    for t in topics:
        if not t["enabled"]:
            continue
        if not t["channels"].get(item["source_type"], False):
            continue
        if any(k and k in text for k in t["keywords"]):
            return t
    return None


def ingest_batch(conn, batch_no, now):
    """接入一批数据，返回统计：接入数、过滤数、合并的水军帖数、涉及的事件。"""
    from ..db.session import rows
    topics = rows(conn, "SELECT * FROM topic ORDER BY id")
    stores = {}
    for st in rows(conn, "SELECT * FROM store ORDER BY id"):
        stores.setdefault(st["topic_id"], []).append(st)
    stats = {"ingested": [], "filtered": 0, "merged": [], "events": set()}
    for item in batch_items(batch_no):
        text = tagging.full_text(item)
        topic = match_topic(topics, item, text)
        if topic is None:
            stats["filtered"] += 1
            continue
        if conn.execute("SELECT 1 FROM content WHERE id = %s", (item["id"],)).fetchone():
            continue
        tags = tagging.tag(item, topic)
        category = sources.source_category(item, topic)
        store = sources.match_store(stores.get(topic["id"], []), text)
        fp = dedup.simhash(item["text"])
        dup_of = dedup.find_duplicate(conn, fp)
        event_id = None
        if dup_of:
            # 水军近似帖：并入首发，首发 dup_count + 1，自己不进统计
            conn.execute("UPDATE content SET dup_count = dup_count + 1 WHERE id = %s", (dup_of,))
            event_id = conn.execute("SELECT event_id FROM content WHERE id = %s", (dup_of,)).fetchone()[0]
            stats["merged"].append({"id": item["id"], "dup_of": dup_of})
        else:
            event_id = dedup.assign_event(conn, item, text, topic, now)
            stats["ingested"].append(item["id"])
            if event_id:
                stats["events"].add(event_id)
        conn.execute(
            """INSERT INTO content(id, event_id, topic_id, source_type, platform, author,
               author_type, kol_weight, published_at, text, media_type, ocr_text, asr_text,
               parent_id, reposts, comments, likes, simhash, sentiment, emotion,
               sensitive_hits, entities, batch_no, dup_of, source_category, store_id, store_subject,
               official_url, investigation_status, handling_result)
               VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                      %s,%s,%s,%s,%s,%s)""",
            (item["id"], event_id, topic["id"], item["source_type"], item.get("platform"),
             item.get("author"), item.get("author_type", "普通"), item.get("kol_weight", 0),
             item["published_at"], item["text"], item.get("media_type", "text"),
             item.get("ocr_text"), item.get("asr_text"), item.get("parent_id"),
             item.get("reposts", 0), item.get("comments", 0), item.get("likes", 0),
             fp, tags["sentiment"], tags["emotion"],
             json.dumps(tags["sensitive_hits"], ensure_ascii=False),
             json.dumps(tags["entities"], ensure_ascii=False), batch_no, dup_of,
             category, store["id"] if store else None,
             item.get("store_subject") or (store["name"] if store else None),
             item.get("official_url"), item.get("investigation_status"), item.get("handling_result")),
        )
    return stats
