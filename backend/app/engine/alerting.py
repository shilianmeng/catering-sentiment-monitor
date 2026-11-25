"""预警模块：三条触发规则 + 静默期去重 + 升级告警。

规则：①单小时负向声量环比激增超阈值 ②本批命中高危敏感词 ③账号权重 ≥9 的大号发声。
同一事件告警后，静默期内（含截止时刻）再触发只记一条「静默期内已抑制」，不推送；
自动等级升级（且此前告过警）不受静默期限制，立即发「升级」告警。
"""
import json
from datetime import datetime, timedelta

from .rating import LEVEL_RANK, hourly_counts
from .tagging import HIGH_RISK_WORDS

FMT = "%Y-%m-%d %H:%M"


def _prev_hour(hour_key):
    t = datetime.strptime(hour_key, "%Y-%m-%d %H") - timedelta(hours=1)
    return t.strftime("%Y-%m-%d %H")


def check_rules(conn, event_id, batch_no, now, cfg):
    """返回本批命中的规则列表 [(类型, 描述)]。"""
    from ..db.session import rows
    contents = rows(conn, "SELECT * FROM content WHERE event_id = %s AND dup_of IS NULL", (event_id,))
    new = [c for c in contents if c["batch_no"] == batch_no]
    hits = []

    neg = hourly_counts(contents, only_negative=True)
    hour = now[:13]
    cur, prev = neg.get(hour, 0), neg.get(_prev_hour(hour), 0)
    if prev > 0 and cur >= cfg["surge_min_count"]:
        growth = (cur - prev) * 100 / prev
        if growth > cfg["surge_threshold"]:
            hits.append(("激增", f"负向声量 {hour[11:13]}:00 时段 {cur} 条，环比上一小时 {prev} 条 "
                               f"增长 {growth:.0f}%（阈值 {cfg['surge_threshold']}%）"))

    words = []
    for c in new:
        for w in c["sensitive_hits"] or []:
            if w in HIGH_RISK_WORDS and w not in words:
                words.append(w)
    if words:
        hits.append(("敏感词", f"命中高危敏感词：{'、'.join(words)}"))

    kols = [c for c in new if c["kol_weight"] >= cfg["kol_alert_weight"]]
    if kols:
        names = "、".join(f"{c['author']}（权重 {c['kol_weight']}）" for c in kols)
        hits.append(("KOL发声", f"高权重账号发声：{names}"))
    return hits


def _notify_channels(cfg):
    ch = []
    if cfg["notify_site"]:
        ch.append("站内通知")
    if cfg["notify_email"]:
        ch.append("邮件（模拟）")
    if cfg["notify_sms"]:
        ch.append("短信（模拟）")
    return ch


def evaluate(conn, event_id, batch_no, now, old_auto, new_auto, cfg):
    """评估一个事件本批是否告警。返回新写入的告警行（含被抑制的），供 SSE 推送。"""
    ev = conn.execute("SELECT title, level FROM event WHERE id = %s", (event_id,)).fetchone()
    last = conn.execute(
        "SELECT silence_until FROM alert WHERE event_id = %s AND suppressed = 0 "
        "ORDER BY id DESC LIMIT 1", (event_id,)).fetchone()
    hits = check_rules(conn, event_id, batch_no, now, cfg)
    upgraded = last is not None and LEVEL_RANK[new_auto] > LEVEL_RANK[old_auto]

    if upgraded:
        alert_type = "升级"
        desc = f"自动等级 {old_auto} → {new_auto}（升级告警不受静默期限制）"
        if hits:
            desc += "；" + "；".join(h[1] for h in hits)
        suppressed = False
    elif hits:
        alert_type = hits[0][0]
        desc = "；".join(h[1] for h in hits)
        suppressed = last is not None and now <= last["silence_until"]
    else:
        return []

    level = ev["level"]
    if suppressed:
        summary = f"【静默期内已抑制】{ev['title']}：{desc}（静默至 {last['silence_until'][11:]}）"
        silence_until = last["silence_until"]
        notified = []
    else:
        verb = "等级升级" if upgraded else f"触发{level}级预警"
        summary = f"{ev['title']}{verb}"
        silence_until = (datetime.strptime(now, FMT)
                         + timedelta(minutes=cfg["silence_minutes"])).strftime(FMT)
        notified = _notify_channels(cfg)

    cur = conn.execute(
        """INSERT INTO alert(event_id, alert_type, rule_desc, level, summary, triggered_at,
           batch_no, silence_until, suppressed, notified) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (event_id, alert_type, desc, level, summary, now, batch_no, silence_until,
         1 if suppressed else 0, json.dumps(notified, ensure_ascii=False)),
    )
    return [cur.lastrowid]
