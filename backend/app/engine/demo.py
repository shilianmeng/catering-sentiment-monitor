"""演示模块：建库灌种子、一键重置、虚拟时钟推进。

推进一批 = 采集 → 打标 → 去重 → 聚合 → 评级 → 观点聚类 → 预警 全链路，结果确定可重复。

演示客户的品牌画像（品牌名、门店、产品、议题规则）全部来自 seed_data.json，
代码里不出现任何品牌名；换演示客户只改那个 JSON 文件。
"""
import json

from . import agent, alerting, collector, rating, sources
from ..collectors import pipeline as official_pipeline
from ..core.config import BATCHES, DEFAULT_CONFIG, LAST_BATCH, SEED_FILE, SOURCE_TYPES, batch_label, batch_time
from ..core.security import hash_password
from ..db.session import (connect, current_batch, drop_all, ensure_database, get_config, has_schema,
                          init_schema, migrate, rows, set_config, write_lock)
from ..repositories import store_repo

DEMO_USERS = [
    ("analyst", "analyst", "分析师·小林"),
    ("pr", "pr", "公关·小周"),
    ("admin", "admin", "管理员·小盟"),
]
DEMO_PASSWORD = "123456"

_seed_cache = None


def load_seed():
    global _seed_cache
    if _seed_cache is None:
        with open(SEED_FILE, encoding="utf-8") as f:
            _seed_cache = json.load(f)
    return _seed_cache


def seed_topics() -> list[dict]:
    """演示客户画像：来自 seed_data.json 的 topics，不在代码里写死。"""
    return load_seed()["topics"]


def _seed_base(conn):
    for username, role, name in DEMO_USERS:
        conn.execute("INSERT INTO user(username, password_hash, role, display_name) VALUES(%s,%s,%s,%s)",
                     (username, hash_password(DEMO_PASSWORD), role, name))
    for t in seed_topics():
        conn.execute(
            "INSERT INTO topic(name, keywords, channels, brand, entities, event_rules, created_by, enabled) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,1)",
            (t["name"], json.dumps(t["keywords"], ensure_ascii=False),
             json.dumps({s: True for s in SOURCE_TYPES}, ensure_ascii=False), t["brand"],
             json.dumps(t.get("entities") or [], ensure_ascii=False),
             json.dumps(t.get("event_rules") or [], ensure_ascii=False), "admin"),
        )
    seed_stores(conn)
    # 官方记录跨重置保留；主题和门店是重建的，旧的关联作废，按新 id 重新挂
    conn.execute("UPDATE official_record SET topic_id = NULL, store_id = NULL")
    official_pipeline.load_seed(conn)
    for k, v in DEFAULT_CONFIG.items():
        set_config(conn, k, v)
    set_config(conn, "current_batch", -1)
    set_config(conn, "filtered_total", 0)


def seed_stores(conn) -> int:
    """按 seed_data.json 的 topics[].stores 建门店；已有同名门店跳过（幂等）。"""
    n = 0
    by_name = {t["name"]: t for t in seed_topics()}
    for row in conn.execute("SELECT id, name FROM topic").fetchall():
        seed = by_name.get(row["name"])
        for st in (seed or {}).get("stores") or []:
            if store_repo.find_by_name(conn, row["id"], st["name"]):
                continue
            store_repo.insert_store(conn, {**st, "topic_id": row["id"]})
            n += 1
    return n


def backfill_store_fields(conn) -> None:
    """老版 store 表用 type 存直营/加盟、region 存大区：迁到 ownership / province，没有别名的补上简称。"""
    cols = {r["COLUMN_NAME"].lower() for r in conn.execute(
        "SELECT COLUMN_NAME FROM information_schema.columns WHERE TABLE_SCHEMA = DATABASE() "
        "AND TABLE_NAME = 'store'").fetchall()}
    if "type" in cols:
        conn.execute("UPDATE store SET ownership = type WHERE type IN ('直营', '加盟') AND ownership <> type")
    if "region" in cols:
        conn.execute("UPDATE store SET province = region WHERE province IS NULL AND region IS NOT NULL")
    for st in rows(conn, "SELECT id, name, aliases FROM store WHERE aliases IS NULL"):
        short = st["name"].split("·")[-1]
        conn.execute("UPDATE store SET aliases = %s WHERE id = %s",
                     (json.dumps([short] if short != st["name"] else [], ensure_ascii=False), st["id"]))


def backfill_content_sources(conn) -> int:
    """老库升级：给还没有来源类别的内容补上来源类别和门店。"""
    topics = {t["id"]: t for t in rows(conn, "SELECT * FROM topic")}
    stores = {}
    for st in rows(conn, "SELECT * FROM store"):
        stores.setdefault(st["topic_id"], []).append(st)
    n = 0
    for c in rows(conn, "SELECT id, topic_id, source_type, author, author_type, text, ocr_text, asr_text "
                        "FROM content WHERE source_category IS NULL"):
        text = "\n".join(x for x in (c["text"], c["ocr_text"], c["asr_text"]) if x)
        store = sources.match_store(stores.get(c["topic_id"], []), text)
        conn.execute("UPDATE content SET source_category = %s, store_id = %s, store_subject = %s WHERE id = %s",
                     (sources.source_category(c, topics.get(c["topic_id"])), store["id"] if store else None,
                      store["name"] if store else None, c["id"]))
        n += 1
    return n


def backfill_profiles(conn):
    """老库升级：给还没有品牌画像的主题补上。

    先在 seed_data.json 里按名称/关键词找对应画像（演示库就是这么来的）；
    找不到就退化成「品牌名 = 第一个关键词、议题规则用行业默认」，不让它跑不起来。
    """
    seeds = seed_topics()
    for row in conn.execute("SELECT id, name, keywords, brand FROM topic").fetchall():
        if row["brand"]:
            continue
        keywords = json.loads(row["keywords"] or "[]")
        matched = next((s for s in seeds
                        if s["name"] == row["name"] or set(s.get("keywords") or []) & set(keywords)), None)
        brand = matched["brand"] if matched else (keywords[0] if keywords else row["name"])
        entities = (matched.get("entities") if matched else None) or []
        rules = (matched.get("event_rules") if matched else None) or []
        conn.execute("UPDATE topic SET brand = %s, entities = %s, event_rules = %s WHERE id = %s",
                     (brand, json.dumps(entities, ensure_ascii=False),
                      json.dumps(rules, ensure_ascii=False), row["id"]))
    conn.commit()


def reset():
    """删表重建，灌入用户/主题/配置，并接入 T0 批次。"""
    ensure_database()
    with write_lock:
        conn = connect()
        try:
            drop_all(conn)
            init_schema(conn)
            _seed_base(conn)
            conn.commit()
        finally:
            conn.close()
        return advance(1)


def ensure_db():
    """首次启动没有库就自动建库并灌种子；老库启动时补新表/新列/品牌画像（幂等）。"""
    conn = connect()
    try:
        ready = has_schema(conn) and conn.execute("SELECT COUNT(*) FROM user").fetchone()[0] > 0
        if ready:
            migrate(conn)
            backfill_profiles(conn)
            backfill_store_fields(conn)
            seed_stores(conn)
            backfill_content_sources(conn)
            official_pipeline.load_seed(conn)       # 按 record_key 去重，重复启动不会重复灌
            conn.commit()
    finally:
        conn.close()
    if not ready:
        reset()


def _advance_one(conn, batch_no, cfg):
    now = batch_time(batch_no)
    stats = collector.ingest_batch(conn, batch_no, now)
    alert_ids, changes = [], []
    for eid in sorted(stats["events"]):
        old_auto, new_auto = rating.recompute(conn, eid, cfg)
        agent.recompute_clusters(conn, eid)
        alert_ids += alerting.evaluate(conn, eid, batch_no, now, old_auto, new_auto, cfg)
        changes.append({"event_id": eid, "from": old_auto, "to": new_auto})
    set_config(conn, "current_batch", batch_no)
    total = get_config(conn).get("filtered_total", 0)
    set_config(conn, "filtered_total", total + stats["filtered"])
    return {
        "batch_no": batch_no, "label": batch_label(batch_no), "time": now,
        "ingested": len(stats["ingested"]), "filtered": stats["filtered"],
        "merged": stats["merged"], "level_changes": changes, "alert_ids": alert_ids,
    }


def advance(batches=1):
    """虚拟时钟往后推进若干批。已到最后一批则不再推进。"""
    with write_lock:
        conn = connect()
        try:
            cfg = get_config(conn)
            results = []
            for _ in range(max(1, int(batches))):
                nxt = current_batch(conn) + 1
                if nxt > LAST_BATCH:
                    break
                results.append(_advance_one(conn, nxt, cfg))
            conn.commit()
            cur = current_batch(conn)
        finally:
            conn.close()
    return {"current_batch": cur, "current_label": batch_label(cur),
            "finished": cur >= LAST_BATCH, "results": results}


def clock_state(conn):
    cur = current_batch(conn)
    return {"current_batch": cur, "current_label": batch_label(cur), "current_time": batch_time(cur),
            "finished": cur >= LAST_BATCH, "batches": BATCHES}


def recompute_all_levels():
    """管理员改了等级分数线后，立即按新阈值重算所有事件（不产生告警）。"""
    with write_lock:
        conn = connect()
        try:
            cfg = get_config(conn)
            for r in conn.execute("SELECT id FROM event").fetchall():
                rating.recompute(conn, r["id"], cfg)
            conn.commit()
        finally:
            conn.close()


_GUARD_COLS = tuple(c for c in official_pipeline._RECORD_COLS) + ("revision",)


def official_fingerprint(conn) -> dict:
    """官方记录的指纹：record_key → 业务字段。重置只允许改 topic_id/store_id（品牌关联会重挂）。"""
    cols = ", ".join(f"`{c}`" for c in _GUARD_COLS)
    if not has_schema(conn):
        return {}
    return {r["record_key"]: {c: r[c] for c in _GUARD_COLS}
            for r in rows(conn, f"SELECT {cols} FROM official_record")}


def backup_official(dest_dir=None) -> tuple[str | None, dict]:
    """重置前把 official_record 整表导出成 JSON（真实证据，丢了要能恢复）。表不存在返回 (None, {})。"""
    import datetime
    from pathlib import Path

    from ..core.config import BACKEND_DIR

    conn = connect()
    try:
        if not has_schema(conn):
            return None, {}
        full = rows(conn, "SELECT * FROM official_record ORDER BY id")
        fp = official_fingerprint(conn)
    finally:
        conn.close()
    if not full:
        return None, fp
    dest = Path(dest_dir) if dest_dir else BACKEND_DIR / "data" / "backups"
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / f"official_record_{datetime.datetime.now():%Y%m%d_%H%M%S}.json"
    path.write_text(json.dumps({"count": len(full), "records": full}, ensure_ascii=False, default=str, indent=1),
                    encoding="utf-8")
    return str(path), fp


def guarded_reset(dest_dir=None) -> dict:
    """命令行 / start.ps1 -Reset 用：先备份官方记录，重置，再逐条核对官方记录没被改动。"""
    path, before = backup_official(dest_dir)
    result = reset()
    conn = connect()
    try:
        after = official_fingerprint(conn)
    finally:
        conn.close()
    lost = sorted(set(before) - set(after))
    changed = sorted(k for k in before if k in after and before[k] != after[k])
    return {**result, "backup": path, "official_before": len(before), "official_after": len(after),
            "official_lost": lost, "official_changed": changed}


if __name__ == "__main__":
    import sys

    if "--reset" in sys.argv:
        result = guarded_reset()
        if result["backup"]:
            print(f"官方处罚记录已备份：{result['backup']}（{result['official_before']} 条）")
        print(f"已重置演示库并接入 {result['current_label']} 批次。")
        if result["official_lost"] or result["official_changed"]:
            print(f"[警告] 官方记录有变化：丢失 {len(result['official_lost'])} 条，"
                  f"改动 {len(result['official_changed'])} 条。用上面的备份恢复。")
            sys.exit(2)
        print(f"官方处罚记录核对一致：重置前 {result['official_before']} 条，重置后 {result['official_after']} 条，"
              f"业务字段无改动。")
    else:
        ensure_db()
        print("数据库已就绪（表结构、演示数据、品牌画像均在）。")
