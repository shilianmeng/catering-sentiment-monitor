"""态势大盘：指标、趋势、情感分布、词云、最新预警。"""
from ..core.config import BATCHES
from ..db.session import current_batch, get_config
from ..engine import demo, profile
from ..engine.tagging import ENTITY_DICT, GENERAL_SENSITIVE_WORDS, HIGH_RISK_WORDS, NEG_WORDS, POS_WORDS
from ..repositories import alert_repo, content_repo, event_repo, topic_repo

# 词云词表：风险词 + 情感词 + 行业实体 + 少量业务词；品牌自有实体（门店/产品）按主题动态追加。
# 只统计词表内的词，避免分词噪声。
_BASE_VOCAB = list(dict.fromkeys(
    HIGH_RISK_WORDS + GENERAL_SENSITIVE_WORDS + NEG_WORDS + POS_WORDS
    + [a for _, (_, aliases) in ENTITY_DICT.items() for a in aliases]
    + ["新品", "道歉", "整改", "视频", "门店"]
))


def _vocab(conn) -> list[str]:
    extra = [a for t in topic_repo.list_topics(conn) for e in profile.entities_of(t) for a in e["aliases"]]
    return list(dict.fromkeys(_BASE_VOCAB + extra))
WORD_TOP_N = 30
ALERT_LIMIT = 12


def _word_freq(contents: list[dict], vocab: list[str]) -> list[dict]:
    freq: dict[str, int] = {}
    for c in contents:
        text = " ".join(x for x in (c["text"], c["ocr_text"], c["asr_text"]) if x)
        for w in vocab:
            k = text.count(w)
            if k:
                freq[w] = freq.get(w, 0) + k
    top = sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))[:WORD_TOP_N]
    return [{"word": w, "count": k} for w, k in top]


def _trend(contents: list[dict], cur: int) -> list[dict]:
    trend = []
    for b in BATCHES:
        if b["no"] > cur:
            break
        bc = [c for c in contents if c["batch_no"] == b["no"]]
        trend.append({"label": b["label"], "time": b["time"][11:], "total": len(bc),
                      "negative": sum(1 for c in bc if c["sentiment"] == "负向"),
                      "positive": sum(1 for c in bc if c["sentiment"] == "正向")})
    return trend


def metrics(conn, contents: list[dict] | None = None) -> dict:
    contents = contents if contents is not None else content_repo.list_for_overview(conn)
    n = len(contents)
    neg = sum(1 for c in contents if c["sentiment"] == "负向")
    alerts, unread = alert_repo.count_alerts(conn)
    return {
        "total": n, "negative": neg,
        "negative_rate": round(neg * 100 / n, 1) if n else 0,
        "active_events": event_repo.count_active(conn), "alerts": alerts, "unread_alerts": unread,
        "merged": content_repo.count_merged(conn),
        "filtered": get_config(conn).get("filtered_total", 0),
    }


def overview(conn) -> dict:
    contents = content_repo.list_for_overview(conn)
    senti = {"正向": 0, "中性": 0, "负向": 0}
    for c in contents:
        senti[c["sentiment"]] = senti.get(c["sentiment"], 0) + 1
    return {
        "metrics": metrics(conn, contents),
        "trend": _trend(contents, current_batch(conn)),
        "sentiment": senti,
        "words": _word_freq(contents, _vocab(conn)),
        "alerts": alert_repo.list_alerts(conn, limit=ALERT_LIMIT),
        "events": event_repo.list_brief(conn),
        "clock": demo.clock_state(conn),
    }
