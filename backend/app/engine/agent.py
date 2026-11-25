"""研判 Agent 模块：观点聚类、公关话术草案、报告文字，统一封装大模型调用与降级。

- 观点聚类按预置规则归类，保证没有 key 也有结果、两次运行一致。
- 有 OPENAI_API_KEY 时调用模型生成文字；没有 key 或调用失败，自动降级为模板生成。
  所有生成结果都带 gen_mode：「模型生成」或「模板生成」。
- key 只从环境变量或 backend/.env 读取（代码里不保存凭据），不写入数据库。
"""
import json

from ..core import config
from ..db.session import rows
from . import profile

CLUSTER_RULES = [
    {"summary": "退款赔偿诉求：要求{brand}退款、赔偿并给出说法", "sentiment": "负向", "emotion": "愤怒",
     "keywords": ["退款", "赔偿", "给个说法", "交代"]},
    {"summary": "要求监管介入：质疑门店管理，呼吁监管部门调查", "sentiment": "负向", "emotion": "质疑",
     "keywords": ["监管", "调查", "谁来管", "查一查", "介入"]},
    {"summary": "品牌信任受损：老顾客失望，表示不会再光顾", "sentiment": "负向", "emotion": "失望",
     "keywords": ["失望", "再也不", "不会再", "粉转黑", "寒心", "以前常去"]},
    {"summary": "食品安全担忧：担心吃过后身体受影响，尤其是孩子", "sentiment": "负向", "emotion": "恐慌",
     "keywords": ["担心", "害怕", "后怕", "不敢", "孩子", "拉肚子", "吓人"]},
    {"summary": "新品口碑好评：认可新品口味与性价比", "sentiment": "正向", "emotion": None,
     "keywords": ["好吃", "推荐", "外酥里嫩", "满意", "回购"]},
]


# ---------- 观点聚类 ----------

def _topic_of_event(conn, event_id) -> dict:
    from ..db.session import one
    row = one(conn, "SELECT t.* FROM event e JOIN topic t ON t.id = e.topic_id WHERE e.id = %s", (event_id,))
    return row or {}


def _brand_of_event(conn, event_id) -> str:
    return profile.brand_of(_topic_of_event(conn, event_id))


def recompute_clusters(conn, event_id):
    brand = _brand_of_event(conn, event_id)
    contents = rows(conn, "SELECT id, text, ocr_text, asr_text, sentiment, reposts, comments, likes "
                          "FROM content WHERE event_id = %s AND dup_of IS NULL ORDER BY published_at, id",
                    (event_id,))
    groups = {i: [] for i in range(len(CLUSTER_RULES))}
    for c in contents:
        text = " ".join(x for x in (c["text"], c["ocr_text"], c["asr_text"]) if x)
        best, best_n = None, 0
        for i, rule in enumerate(CLUSTER_RULES):
            if rule["sentiment"] != c["sentiment"]:
                continue
            n = sum(text.count(k) for k in rule["keywords"])
            if n > best_n:
                best, best_n = i, n
        if best is not None:
            groups[best].append(c)
    conn.execute("DELETE FROM opinion_cluster WHERE event_id = %s", (event_id,))
    for i, members in groups.items():
        if not members:
            continue
        rule = CLUSTER_RULES[i]
        reps = sorted(members, key=lambda c: (-(c["reposts"] + c["comments"] + c["likes"]), c["id"]))[:3]
        conn.execute(
            "INSERT INTO opinion_cluster(event_id, summary, sentiment, emotion, "
            "representative_content_ids, count) VALUES(%s,%s,%s,%s,%s,%s)",
            (event_id, rule["summary"].replace("{brand}", brand), rule["sentiment"], rule["emotion"],
             json.dumps([c["id"] for c in reps]), len(members)),
        )


def clusters_with_quotes(conn, event_id):
    out = rows(conn, "SELECT * FROM opinion_cluster WHERE event_id = %s ORDER BY count DESC, id",
               (event_id,))
    for cl in out:
        cl["quotes"] = []
        for cid in cl["representative_content_ids"]:
            r = conn.execute("SELECT id, author, text FROM content WHERE id = %s", (cid,)).fetchone()
            if r:
                cl["quotes"].append(dict(r))
    return out


# ---------- 大模型调用与降级 ----------

def llm_available():
    return bool(config.OPENAI_API_KEY)


def call_llm(prompt, model, system="你是资深的品牌舆情分析师，输出简体中文，内容务实、克制、可直接使用。"):
    """调用模型；没有 key 或任何异常都返回 None，由调用方降级到模板。"""
    if not llm_available():
        return None
    try:
        from openai import OpenAI
        client = OpenAI(api_key=config.OPENAI_API_KEY, timeout=30)
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            temperature=0.3,
        )
        text = (resp.choices[0].message.content or "").strip()
        return text or None
    except Exception as e:  # noqa: BLE001 —— 网络、额度、模型名错误都降级
        print(f"[agent] 模型调用失败，降级为模板生成：{type(e).__name__}: {e}")
        return None


def event_brief(conn, event_id):
    ev = dict(conn.execute("SELECT * FROM event WHERE id = %s", (event_id,)).fetchone())
    stats = conn.execute(
        "SELECT COUNT(*) n, SUM(sentiment='负向') neg FROM content WHERE event_id = %s AND dup_of IS NULL",
        (event_id,)).fetchone()
    first = conn.execute("SELECT * FROM content WHERE id = %s", (ev["first_content_id"],)).fetchone()
    return ev, stats["n"] or 0, stats["neg"] or 0, (dict(first) if first else None)


# ---------- 话术草案 ----------

def _store_of_event(conn, event_id, topic) -> str:
    """从内容里找涉事门店（客户画像里的门店实体），找不到就用中性说法。"""
    for r in conn.execute("SELECT text, ocr_text, asr_text FROM content "
                          "WHERE event_id = %s AND dup_of IS NULL", (event_id,)).fetchall():
        found = profile.store_in(topic, " ".join(x for x in r.values() if x))
        if found:
            return found
    return "涉事门店"


def template_draft(conn, event_id):
    ev, n, neg, first = event_brief(conn, event_id)
    topic = _topic_of_event(conn, event_id)
    clusters = clusters_with_quotes(conn, event_id)
    concerns = "、".join(c["summary"].split("：")[0] for c in clusters if c["sentiment"] == "负向") or "公众关切"
    store = _store_of_event(conn, event_id, topic)
    issue = ev["category"] or "食品安全"
    return (
        f"## 一、事实澄清\n"
        f"关于网络上反映的{store}{issue}问题，我们高度重视。经初步核查，{store}已于即日起暂停营业、"
        f"全面整改，涉事批次食材已全部封存下架，并主动配合有关部门检查。核查结论将第一时间公开。\n\n"
        f"## 二、情绪疏导\n"
        f"我们注意到大家集中关心的是：{concerns}。对此造成的担忧和不便，我们诚恳致歉。"
        f"每一位顾客的健康都是我们的底线，我们理解大家的愤怒与失望，也接受所有批评。\n\n"
        f"## 三、行动方案\n"
        f"1. 近 7 日在{store}消费的顾客，可凭订单或小票申请全额退款，客服热线 24 小时受理；\n"
        f"2. 对全国门店开展{issue}专项自查，邀请第三方机构与消费者代表参与，并公开结果；\n"
        f"3. 欢迎社会和媒体监督，整改进展每 48 小时在官方账号更新一次。\n"
    )


def generate_draft(conn, event_id, cfg):
    tpl = template_draft(conn, event_id)
    ev, n, neg, first = event_brief(conn, event_id)
    clusters = clusters_with_quotes(conn, event_id)
    prompt = (
        f"事件：{ev['title']}，当前等级 {ev['level']}，相关内容 {n} 条，其中负向 {neg} 条。\n"
        f"首发：{first['author'] if first else '-'}：{first['text'] if first else '-'}\n"
        f"主要观点：\n" + "\n".join(f"- {c['summary']}（{c['count']} 条）" for c in clusters) +
        "\n请写一份公关回应话术草案，严格分三段，用 Markdown 二级标题："
        "## 一、事实澄清 / ## 二、情绪疏导 / ## 三、行动方案。不要编造未经核实的结论，300 字以内。"
    )
    text = call_llm(prompt, cfg["llm_model"])
    if text:
        return text, "模型生成", cfg["llm_model"]
    return tpl, "模板生成", None


# ---------- 报告文字（风险研判 + 应对建议） ----------

def report_narrative(conn, event_id, template_risk, template_advice, cfg):
    ev, n, neg, first = event_brief(conn, event_id)
    prompt = (
        f"事件：{ev['title']}，等级 {ev['level']}，烈度 {ev['intensity_score']}，"
        f"相关内容 {n} 条（负向 {neg} 条）。\n已有数据结论：\n{template_risk}\n\n{template_advice}\n\n"
        "请在不改变任何数字和 content id 引用（形如 [c001]）的前提下，把上面两部分润色成正式报告语言，"
        "严格按以下顺序输出：风险研判结论标题、风险正文、单独一行 ===、应对与处置建议标题、建议正文。"
        "分隔符只能出现在两段正文之间，不得放在末尾；两段正文都不能为空。"
    )
    text = call_llm(prompt, cfg["llm_model"])
    if text and "===" in text:
        risk, advice = text.split("===", 1)
        clean = lambda s: "\n".join(l for l in s.strip().splitlines()
                                    if l.strip().lstrip("#").strip() not in ("风险研判结论", "应对与处置建议"))
        risk, advice = clean(risk), clean(advice)
        if risk and advice:
            return risk, advice, "模型生成", cfg["llm_model"]
    return template_risk, template_advice, "模板生成", None
