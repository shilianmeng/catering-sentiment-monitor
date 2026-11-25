"""门店风险评分（第③步）：官方通报按处理结果分级、投诉按每百店折算，风险落到具体门店。

和事件烈度（rating.py）是两套东西：烈度看传播，这里看门店本身有没有被监管处理过、被投诉得多不多。

一、官方通报分级（不算情绪分，只看官方写明的处理结果）
    档位            基础分  判定
    移送公安         50     调查状态是「公安已立案 / 已移送公安」，或处理结果写了移送公安
    罚没处罚         30     处理结果有罚款（不含「拟罚款」）或没收；按金额另加 0–15 分
    立案调查         20     只写了立案、还没有处理结果
    警告/责令整改    10     只有警告、责令改正
  - 罚款加分 = 5 × log10(金额 / 1000)，1 千元 0 分、1 万 5 分、10 万 10 分、100 万封顶 15 分。
  - 吊销许可证、责令停业另加 10 分。
  - 「拟罚款」是处罚告知阶段，不是最终决定，不算罚没。

二、时间衰减：按公告发布日期 published_at 算，不用处理日期。
  处理日期很多公告没写（第②步只认原文写明的日期，30/54 有值），用它会让一半记录没法衰减。
  官方记录半衰期 365 天，投诉 90 天。

三、投诉：来源类别为「顾客投诉」、已落到门店、不是水军合并帖的内容，每条 3 分。
  「顾客投诉」类别里也有夸店的评价，明确是正向的不计；这里只拿情感当过滤条件，不按情绪强弱打分。
  媒体报道只存元数据，不计分，只列条数；品牌回应是品牌自己的声明，也不计分。

四、门店总分 = min(官方, 70) + min(投诉, 30)，0–100。≥60 高、≥30 中、>0 低、0 无。

五、品牌汇总：投诉、官方记录按每百店折算（总数 ÷ 门店数 × 100），直营 / 加盟分开算。
  官方记录认出了品牌、但分不清是哪家店的，单列在品牌下，不摊到门店——宁可留空不挂错。
"""
import math
import re
from datetime import date, datetime

TIER_POLICE, TIER_FINE, TIER_CASE, TIER_ORDER = "移送公安", "罚没处罚", "立案调查", "警告/责令整改"
TIER_BASE = {TIER_POLICE: 50, TIER_FINE: 30, TIER_CASE: 20, TIER_ORDER: 10}
TIER_RANK = {TIER_ORDER: 0, TIER_CASE: 1, TIER_FINE: 2, TIER_POLICE: 3}
FINE_BONUS_CAP = 15
SUSPEND_BONUS = 10
OFFICIAL_HALF_LIFE_DAYS = 365
COMPLAINT_HALF_LIFE_DAYS = 90
POINTS_PER_COMPLAINT = 3
OFFICIAL_CAP = 70
COMPLAINT_CAP = 30
LEVEL_HIGH, LEVEL_MID = 60, 30

_POLICE = re.compile(r"移送公安|公安已立案|公安机关立案")
_FINAL_FINE = re.compile(r"(?<!拟)罚款|没收")
_SUSPEND = re.compile(r"吊销|责令停业|责令停产停业")
_CASE_ONLY = re.compile(r"立案")


def _to_date(value) -> date | None:
    """接受 date / datetime / 'YYYY-MM-DD[ HH:MM]'；只到月份的（'2023-12'）按当月 1 日。"""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()
    for fmt, n in (("%Y-%m-%d", 10), ("%Y-%m", 7)):
        try:
            return datetime.strptime(s[:n], fmt).date()
        except ValueError:
            continue
    return None


def decay(published_at, as_of, half_life_days: int) -> float:
    """按发布日期指数衰减：当天 1，过一个半衰期 0.5。没有日期或日期在 as_of 之后按 1（不打折）。"""
    pub, ref = _to_date(published_at), _to_date(as_of)
    if pub is None or ref is None:
        return 1.0
    age = max(0, (ref - pub).days)
    return 0.5 ** (age / half_life_days)


def fine_bonus(amount) -> float:
    if not amount or amount < 1000:
        return 0.0
    return round(min(FINE_BONUS_CAP, 5 * math.log10(amount / 1000)), 1)


def grade_record(rec: dict) -> dict:
    """一条官方记录的档位和基础分（不含时间衰减）。只看调查状态和处理结果，不看情绪。"""
    status = rec.get("investigation_status") or ""
    result = rec.get("handling_result") or ""
    text = f"{status}；{result}"
    reasons = []
    if _POLICE.search(text):
        tier = TIER_POLICE
        reasons.append("移送公安")
    elif _FINAL_FINE.search(result):
        tier = TIER_FINE
        reasons.append("罚款/没收")
    elif _CASE_ONLY.search(text):
        tier = TIER_CASE
        reasons.append("已立案、无处理结果")
    else:
        tier = TIER_ORDER
        reasons.append("警告/责令改正")
    if "拟罚款" in result:
        reasons.append("拟罚款为告知阶段，不计罚没")
    bonus = fine_bonus(rec.get("fine_amount")) if tier in (TIER_FINE, TIER_POLICE) else 0.0
    if bonus:
        reasons.append(f"罚款 {rec['fine_amount']:,.0f} 元 +{bonus}")
    if _SUSPEND.search(result):
        bonus += SUSPEND_BONUS
        reasons.append(f"吊销/停业 +{SUSPEND_BONUS}")
    return {"tier": tier, "base": TIER_BASE[tier] + bonus, "reason": "；".join(reasons)}


def score_official(rec: dict, as_of) -> dict:
    g = grade_record(rec)
    k = decay(rec.get("published_at"), as_of, OFFICIAL_HALF_LIFE_DAYS)
    return {**g, "decay": round(k, 3), "points": round(g["base"] * k, 1)}


def is_complaint(content: dict) -> bool:
    return (content.get("source_category") == "顾客投诉" and not content.get("dup_of")
            and content.get("sentiment") != "正向")


def level_of(score: float) -> str:
    if score >= LEVEL_HIGH:
        return "高"
    if score >= LEVEL_MID:
        return "中"
    return "低" if score > 0 else "无"


def score_store(store: dict, officials: list[dict], contents: list[dict], as_of) -> dict:
    """一家门店的风险：officials 是挂到这家店的官方记录，contents 是落到这家店的内容（含各来源类别）。"""
    off_items = []
    for r in officials:
        s = score_official(r, as_of)
        off_items.append({"id": r.get("id"), "subject": r.get("subject"), "case_title": r.get("case_title"),
                          "official_url": r.get("official_url"), "published_at": r.get("published_at"),
                          "investigation_status": r.get("investigation_status"),
                          "handling_result": r.get("handling_result"), **s})
    off_items.sort(key=lambda x: (-x["points"], str(x["published_at"] or "")))
    off_raw = round(sum(x["points"] for x in off_items), 1)

    complaints = [c for c in contents if is_complaint(c)]
    comp_raw = round(sum(POINTS_PER_COMPLAINT * decay(c.get("published_at"), as_of, COMPLAINT_HALF_LIFE_DAYS)
                         for c in complaints), 1)
    off_score, comp_score = min(OFFICIAL_CAP, off_raw), min(COMPLAINT_CAP, comp_raw)
    total = round(off_score + comp_score)
    worst = max((x["tier"] for x in off_items), key=TIER_RANK.get, default=None)
    return {
        "store_id": store["id"], "name": store["name"], "ownership": store.get("ownership"),
        "district": store.get("district"), "status": store.get("status"),
        "score": total, "level": level_of(total),
        "official_score": off_score, "official_raw": off_raw, "official_count": len(off_items),
        "worst_tier": worst,
        "complaint_score": comp_score, "complaint_raw": comp_raw, "complaint_count": len(complaints),
        "media_count": sum(1 for c in contents if c.get("source_category") == "媒体报道" and not c.get("dup_of")),
        "brand_response_count": sum(1 for c in contents
                                    if c.get("source_category") == "品牌回应" and not c.get("dup_of")),
        "officials": off_items,
        "complaint_ids": [c.get("id") for c in complaints],
    }


def per_100(n: int, stores: int) -> float | None:
    return round(n * 100 / stores, 1) if stores else None


def brand_summary(stores: list[dict], store_scores: list[dict], unlinked_officials: list[dict],
                  unattributed_complaints: int, as_of) -> dict:
    """品牌层：每百店折算 + 直营/加盟对比 + 认出品牌但没落到门店的官方记录。"""
    n = len(stores)
    comp_total = sum(s["complaint_count"] for s in store_scores) + unattributed_complaints
    off_total = sum(s["official_count"] for s in store_scores) + len(unlinked_officials)
    by_owner = {}
    for own in sorted({s.get("ownership") for s in store_scores if s.get("ownership")}):
        grp = [s for s in store_scores if s.get("ownership") == own]
        by_owner[own] = {
            "stores": len(grp),
            "complaints": sum(s["complaint_count"] for s in grp),
            "complaints_per_100_stores": per_100(sum(s["complaint_count"] for s in grp), len(grp)),
            "officials": sum(s["official_count"] for s in grp),
            "officials_per_100_stores": per_100(sum(s["official_count"] for s in grp), len(grp)),
            "avg_score": round(sum(s["score"] for s in grp) / len(grp), 1),
        }
    ranked = sorted(store_scores, key=lambda s: (-s["score"], s["store_id"]))
    return {
        "as_of": str(_to_date(as_of)),
        "store_count": n,
        "complaints_total": comp_total,
        "complaints_unattributed": unattributed_complaints,
        "complaints_per_100_stores": per_100(comp_total, n),
        "officials_total": off_total,
        "officials_per_100_stores": per_100(off_total, n),
        "by_ownership": by_owner,
        "levels": {lv: sum(1 for s in store_scores if s["level"] == lv) for lv in ("高", "中", "低", "无")},
        "stores": ranked,
        "unlinked_officials": [{"id": r.get("id"), "subject": r.get("subject"),
                                "official_url": r.get("official_url"), **score_official(r, as_of)}
                               for r in unlinked_officials],
    }
