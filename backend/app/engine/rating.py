"""烈度评级模块：四因子各 0–25 分，合计烈度指数 0–100，映射 S/A/B/C。

- 扩散速度：事件单小时新增条数的峰值（水军合并帖不计）
- 互动量：全部内容转评赞总和取对数归一
- KOL 权重：参与账号的最高权重 × 2.5
- 敏感词：事件内出现过的不同敏感词，高危词每个 6 分、一般词每个 2 分

四项都只增不减，所以自动等级不会因为热度回落而倒退。
人工改级后 manual_override = 1，自动重算只更新 auto_* 字段，不覆盖人工等级。
"""
import json
import math

from .tagging import HIGH_RISK_WORDS

SPEED_PER_ITEM = 1.25          # 每小时 1 条 = 1.25 分，20 条封顶
INTERACTION_CAP = 1_000_000    # 互动总量达到 100 万封顶
LEVEL_RANK = {"C": 0, "B": 1, "A": 2, "S": 3}


def level_of(score, cfg):
    if score >= cfg["level_s"]:
        return "S"
    if score >= cfg["level_a"]:
        return "A"
    if score >= cfg["level_b"]:
        return "B"
    return "C"


def hourly_counts(contents, only_negative=False):
    counts = {}
    for c in contents:
        if only_negative and c["sentiment"] != "负向":
            continue
        hour = c["published_at"][:13]
        counts[hour] = counts.get(hour, 0) + 1
    return counts


def compute_scores(contents):
    """contents：事件下的非重复内容。返回四项分和依据。"""
    hourly = hourly_counts(contents)
    peak_hour, peak = max(hourly.items(), key=lambda kv: (kv[1], kv[0])) if hourly else ("-", 0)
    s_speed = min(25, round(peak * SPEED_PER_ITEM))

    inter = sum(c["reposts"] + c["comments"] + c["likes"] for c in contents)
    s_inter = min(25, round(25 * math.log10(1 + inter) / math.log10(1 + INTERACTION_CAP)))

    top = max(contents, key=lambda c: (c["kol_weight"], c["id"])) if contents else None
    max_w = top["kol_weight"] if top else 0
    s_kol = min(25, round(max_w * 2.5))

    words = []
    for c in contents:
        for w in c["sensitive_hits"] or []:
            if w not in words:
                words.append(w)
    high = [w for w in words if w in HIGH_RISK_WORDS]
    general = [w for w in words if w not in HIGH_RISK_WORDS]
    s_sens = min(25, len(high) * 6 + len(general) * 2)

    basis = {
        "speed": f"峰值小时 {peak_hour[11:13] + ':00' if peak_hour != '-' else '-'} 新增 {peak} 条",
        "interaction": f"转评赞合计 {inter:,}",
        "kol": f"最高账号权重 {max_w}（{top['author'] if top else '-'}）",
        "sensitive": f"高危词 {'、'.join(high) or '无'}；一般敏感词 {'、'.join(general) or '无'}",
    }
    return {
        "score_speed": s_speed, "score_interaction": s_inter,
        "score_kol": s_kol, "score_sensitive": s_sens,
        "total": s_speed + s_inter + s_kol + s_sens,
        "peak_volume": peak, "basis": basis,
    }


def recompute(conn, event_id, cfg):
    """重算事件烈度。返回 (旧自动等级, 新自动等级)。"""
    from ..db.session import rows
    contents = rows(conn, "SELECT * FROM content WHERE event_id = %s AND dup_of IS NULL", (event_id,))
    old = conn.execute("SELECT auto_level, manual_override, manual_level FROM event WHERE id = %s",
                       (event_id,)).fetchone()
    s = compute_scores(contents)
    auto_level = level_of(s["total"], cfg)
    level = old["manual_level"] if old["manual_override"] else auto_level
    conn.execute(
        """UPDATE event SET score_speed=%s, score_interaction=%s, score_kol=%s, score_sensitive=%s,
           score_basis=%s, auto_level=%s, auto_score=%s, intensity_score=%s, level=%s, peak_volume=%s
           WHERE id=%s""",
        (s["score_speed"], s["score_interaction"], s["score_kol"], s["score_sensitive"],
         json.dumps(s["basis"], ensure_ascii=False), auto_level, s["total"], s["total"],
         level, s["peak_volume"], event_id),
    )
    return old["auto_level"], auto_level
