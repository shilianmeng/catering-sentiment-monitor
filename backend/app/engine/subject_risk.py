"""主体风险评分（第③步·真实数据版）：以营业执照主体为单位，给带企业全名的官方处罚记录打分排名。

为什么不按门店：越秀双公示 235 条餐饮处罚里，217 个主体几乎都是单店，挂不出「一个品牌多家门店」。
主体（统一社会信用代码）是官方记录里唯一可靠的身份，按它归并不会挂错。

规则沿用 store_risk：每条记录的档位、罚款加分、吊销加分、按 published_at 一年减半，完全一样。
区别只有两点：
- 没有投诉部分（没有合规公开的投诉来源，不编数据），主体分 = min(官方合计, 70)，等级阈值不变；
- 每条记录多一个「违法类别」，只用于画像和筛选，不改分值——
  双公示里同一主体可能是食品安全被罚，也可能是没办登记、占道摆摊、消防备案，面试演示时要分得开。

违法类别优先看详情接口的 cfWfxw（违法行为类型），再看处罚机关和案情原文。
"""
import re
from collections import Counter, defaultdict

from . import store_risk as sr

CAT_FOOD = "食品安全"
CAT_FIRE = "消防安全"
CAT_CITY = "市容/占道"
CAT_TOBACCO = "烟草专卖"
CAT_LICENSE = "登记/证照"
CAT_MARKET = "广告/商标/价格"
CAT_LABOR = "劳动用工"
CAT_CULTURE = "文化/娱乐/文物"
CAT_OTHER = "其他"
CATEGORIES = (CAT_FOOD, CAT_FIRE, CAT_CITY, CAT_TOBACCO, CAT_LICENSE, CAT_MARKET, CAT_LABOR, CAT_CULTURE,
              CAT_OTHER)

# 顺序即优先级：先认处罚机关（消防队、烟草局、街道办的职责很专），再认违法行为类型和案情
_RULES = [
    (CAT_FIRE, ("dept",), re.compile(r"消防")),
    (CAT_TOBACCO, ("dept",), re.compile(r"烟草")),
    (CAT_LABOR, ("dept",), re.compile(r"人力资源和社会保障")),
    (CAT_CULTURE, ("dept",), re.compile(r"文化广电旅游")),
    (CAT_FIRE, ("wfxw",), re.compile(r"消防")),
    (CAT_CITY, ("wfxw",), re.compile(r"市容|设摊|占道|门窗和外墙")),
    (CAT_FOOD, ("wfxw",), re.compile(r"餐饮服务经营者|食品")),
    (CAT_LICENSE, ("wfxw",), re.compile(r"登记|营业执照")),
    (CAT_MARKET, ("wfxw",), re.compile(r"宣传|广告|商标|价格|计量")),
    # 街道办也执行消防法（消防验收备案、抽查不合格仍使用），案由引了消防法就是消防，不能按机关归成市容
    (CAT_FIRE, ("text",), re.compile(r"消防法")),
    (CAT_CITY, ("dept",), re.compile(r"街道办事处|城市管理")),
    (CAT_FOOD, ("text",), re.compile(r"食品安全法|食品经营|餐饮服务|食品")),
    (CAT_LICENSE, ("text",), re.compile(r"市场主体登记|营业执照|未经登记")),
    (CAT_MARKET, ("text",), re.compile(r"广告法|商标|价格|虚假宣传")),
]

_CREDIT = re.compile(r"统一社会信用代码\s*([0-9A-Z]{18})")


def classify(rec: dict) -> str:
    fields = {"dept": rec.get("enforcement_dept") or "", "wfxw": rec.get("violation_type") or "",
              "text": f"{rec.get('violation') or ''}{rec.get('regulation_text') or ''}"}
    for cat, keys, pat in _RULES:
        if any(pat.search(fields[k]) for k in keys):
            return cat
    return CAT_OTHER


def subject_key(rec: dict) -> str:
    """主体身份：统一社会信用代码；没有代码的退回到全名（不做模糊归并，宁可拆开不挂错）。"""
    code = rec.get("credit_code")
    if not code:
        m = _CREDIT.search(rec.get("article_title") or "")
        code = m.group(1) if m else None
    return code or f"name:{(rec.get('subject') or '').strip()}"


def _year(v) -> str | None:
    d = sr._to_date(v)
    return str(d.year) if d else None


def score_subject(records: list[dict], as_of) -> dict:
    """一个主体的全部记录 → 分数、等级、逐条明细（档位、衰减、得分理由、类别、原文链接）。"""
    items = []
    for r in records:
        s = sr.score_official(r, as_of)
        items.append({"id": r.get("id"), "doc_no": r.get("doc_no"), "official_url": r.get("official_url"),
                      "published_at": r.get("published_at"), "enforcement_dept": r.get("enforcement_dept"),
                      "category": r.get("category") or classify(r), "violation_type": r.get("violation_type"),
                      "handling_result": r.get("handling_result"), "fine_amount": r.get("fine_amount"), **s})
    items.sort(key=lambda x: (-x["points"], str(x["published_at"] or "")))
    raw = round(sum(x["points"] for x in items), 1)
    score = round(min(sr.OFFICIAL_CAP, raw))
    names = [r.get("subject") for r in sorted(records, key=lambda r: str(r.get("published_at") or ""))]
    key = subject_key(records[0])
    return {
        "subject_key": key, "credit_code": None if key.startswith("name:") else key,
        "subject": names[-1], "former_names": sorted(set(names[:-1]) - {names[-1]}),
        "score": score, "level": sr.level_of(score), "official_raw": raw,
        "record_count": len(items),
        "fine_total": round(sum(x["fine_amount"] or 0 for x in items), 2),
        "worst_tier": max((x["tier"] for x in items), key=sr.TIER_RANK.get, default=None),
        "categories": dict(Counter(x["category"] for x in items).most_common()),
        "first_at": min((str(x["published_at"]) for x in items if x["published_at"]), default=None),
        "last_at": max((str(x["published_at"]) for x in items if x["published_at"]), default=None),
        "complaint_score": None, "complaint_note": "暂无合规公开的投诉数据源，不计投诉分",
        "records": items,
    }


def group(records: list[dict]) -> dict[str, list[dict]]:
    out = defaultdict(list)
    for r in records:
        out[subject_key(r)].append(r)
    return out


def rank(records: list[dict], as_of, category: str | None = None) -> list[dict]:
    """按主体归并 → 打分 → 排名。category 只保留该类别的记录再打分（看「食品安全风险」时用）。"""
    recs = [{**r, "category": r.get("category") or classify(r)} for r in records]
    if category:
        recs = [r for r in recs if r["category"] == category]
    scored = [score_subject(v, as_of) for v in group(recs).values()]
    scored.sort(key=lambda s: (-s["official_raw"], -s["record_count"], s["subject_key"]))
    for i, s in enumerate(scored, 1):
        s["rank"] = i
    return scored


def profile(records: list[dict], as_of, top: int = 10) -> dict:
    """区域画像：类别、档位、年份、处罚机关分布，罚款最高、反复被罚的主体。脱敏数据也能做，这里是全名数据。"""
    recs = [{**r, "category": r.get("category") or classify(r)} for r in records]
    graded = [(r, sr.grade_record(r)) for r in recs]
    ranked = rank(recs, as_of)
    by_cat = {}
    for cat in CATEGORIES:
        grp = [(r, g) for r, g in graded if r["category"] == cat]
        if not grp:
            continue
        fines = [r["fine_amount"] for r, _ in grp if r.get("fine_amount")]
        by_cat[cat] = {"records": len(grp), "fined": len(fines), "fine_total": round(sum(fines), 2),
                       "tiers": dict(Counter(g["tier"] for _, g in grp))}
    years = defaultdict(lambda: {"records": 0, "fine_total": 0.0})
    for r in recs:
        y = _year(r.get("published_at")) or "未知"
        years[y]["records"] += 1
        years[y]["fine_total"] = round(years[y]["fine_total"] + (r.get("fine_amount") or 0), 2)
    brief = ("rank", "subject_key", "subject", "score", "level", "record_count", "fine_total", "worst_tier",
             "categories", "last_at")
    return {
        "as_of": str(sr._to_date(as_of)),
        "record_count": len(recs), "subject_count": len(ranked),
        "fined_count": sum(1 for r in recs if r.get("fine_amount")),
        "fine_total": round(sum(r.get("fine_amount") or 0 for r in recs), 2),
        "levels": {lv: sum(1 for s in ranked if s["level"] == lv) for lv in ("高", "中", "低", "无")},
        "tiers": dict(Counter(g["tier"] for _, g in graded)),
        "by_category": by_cat,
        "by_year": dict(sorted(years.items())),
        "by_dept": dict(Counter(r.get("enforcement_dept") or "未知" for r in recs).most_common()),
        "reparsed_count": sum(1 for r in recs if r.get("reparsed")),
        "repeat_subjects": [{k: s[k] for k in brief} for s in ranked if s["record_count"] >= 2],
        "top_subjects": [{k: s[k] for k in brief} for s in ranked[:top]],
        "top_fines": sorted(({"id": r.get("id"), "subject": r.get("subject"), "doc_no": r.get("doc_no"),
                              "fine_amount": r["fine_amount"], "category": r["category"],
                              "handling_result": r.get("handling_result"), "official_url": r.get("official_url"),
                              "published_at": r.get("published_at")}
                             for r in recs if r.get("fine_amount")),
                            key=lambda x: -x["fine_amount"])[:top],
    }
