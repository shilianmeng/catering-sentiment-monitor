"""报告模块：按 2.2.8 五节组装结构化研判报告 + 处置记录附表，导出 Markdown / PDF。

每条结论都挂 content id（形如 [c001]）或具体数据。PDF 用 fpdf2 + 系统中文字体：
先用 simhei.ttf，没有再用 msyh.ttc，保证中文不乱码。
"""
import json
import os
import re
from pathlib import Path

from . import agent, trace
from ..core.config import BATCHES, batch_label
from ..db.session import current_batch, rows
from .rating import hourly_counts

FONT_CANDIDATES = [
    Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "simhei.ttf",
    Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "msyh.ttc",
    Path("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"),
    Path("/System/Library/Fonts/PingFang.ttc"),
]


def _volume_series(contents, upto=None):
    """按批次统计声量（每批次的新增条数），给曲线和 PDF 柱状图用。

    只统计到 upto 批（默认当前虚拟时钟所在批次），还没到的批次不出现在曲线上。
    """
    if upto is None:
        upto = max((c["batch_no"] for c in contents), default=-1)
    out = []
    for b in BATCHES:
        if b["no"] > upto:
            break
        n = sum(1 for c in contents if c["batch_no"] == b["no"])
        neg = sum(1 for c in contents if c["batch_no"] == b["no"] and c["sentiment"] == "负向")
        out.append({"label": b["label"], "time": b["time"][11:], "total": n, "negative": neg})
    return out


def build_report(conn, event_id, cfg):
    ev = dict(conn.execute("SELECT * FROM event WHERE id = %s", (event_id,)).fetchone())
    ev["score_basis"] = json.loads(ev["score_basis"] or "{}")
    contents = rows(conn, "SELECT * FROM content WHERE event_id = %s AND dup_of IS NULL "
                          "ORDER BY published_at, id", (event_id,))
    merged = conn.execute("SELECT COUNT(*) FROM content WHERE event_id = %s AND dup_of IS NOT NULL",
                          (event_id,)).fetchone()[0]
    topic = conn.execute("SELECT name FROM topic WHERE id = %s", (ev["topic_id"],)).fetchone()
    n = len(contents)
    neg = sum(1 for c in contents if c["sentiment"] == "负向")
    pos = sum(1 for c in contents if c["sentiment"] == "正向")
    sources = sorted({c["source_type"] for c in contents})
    period = f"{contents[0]['published_at']} 至 {contents[-1]['published_at']}" if contents else "-"
    tl = trace.timeline(conn, event_id)
    clusters = agent.clusters_with_quotes(conn, event_id)
    series = _volume_series(contents, current_batch(conn))
    peak = max(series, key=lambda s: s["total"]) if series else None
    first = next((x for x in tl["nodes"] if "首发" in x["marks"]), None)
    keys = [x for x in tl["nodes"] if "KOL引爆" in x["marks"] or "互动拐点" in x["marks"]]
    alerts = rows(conn, "SELECT * FROM alert WHERE event_id = %s AND suppressed = 0 ORDER BY id", (event_id,))
    disposals = rows(conn, "SELECT * FROM disposal_action WHERE event_id = %s ORDER BY id", (event_id,))
    adopted = conn.execute("SELECT content FROM response_draft WHERE event_id = %s AND adopted = 1 "
                           "ORDER BY id DESC LIMIT 1", (event_id,)).fetchone()

    # 一、事件基本信息
    s1 = (
        f"| 项目 | 内容 |\n|---|---|\n"
        f"| 事件 | {ev['title']}（{ev['id']}） |\n"
        f"| 监测主题 | {topic['name'] if topic else '-'} |\n"
        f"| 监测周期 | {period}（虚拟时间） |\n"
        f"| 覆盖信源 | {'、'.join(sources)}（共 {len(sources)} 类，模拟数据） |\n"
        f"| 总声量 | {n} 条（另合并水军近似帖 {merged} 条，不计入） |\n"
        f"| 负面率 | {neg * 100 / n if n else 0:.1f}%（负向 {neg} / 正向 {pos} / 中性 {n - neg - pos}） |\n"
        f"| 当前等级 | {ev['level']} 级，烈度指数 {ev['intensity_score']}"
        f"{'（人工调整，自动 ' + ev['auto_level'] + ' 级）' if ev['manual_override'] else ''} |\n"
        f"| 处置状态 | {ev['status']} |\n"
    )

    # 二、传播态势分析
    curve = " → ".join(f"{s['label']} {s['total']}" for s in series)
    s2 = f"**声量曲线（各批次新增条数）**：{curve}。\n\n"
    if peak:
        s2 += f"**声量峰值**：{peak['label']}（{peak['time']}）单批新增 {peak['total']} 条，其中负向 {peak['negative']} 条。\n\n"
    if first:
        s2 += (f"**首发**：{first['published_at'][11:]} {first['author']}（{first['platform']}，"
               f"权重 {first['kol_weight']}）发布{ '短视频' if first['media_type'] == 'video' else '内容'}"
               f"「{first['text'][:30]}…」[{first['id']}]。\n\n")
    if keys:
        s2 += "**关键拐点与意见领袖**：\n" + "".join(
            f"- {k['published_at'][11:]} {k['author']}（{k['platform']}，权重 {k['kol_weight']}，"
            f"互动 {k['interaction']:,}）—— {'、'.join(k['marks'])} [{k['id']}]\n" for k in keys)
    if alerts:
        s2 += "\n**预警记录**：\n" + "".join(
            f"- {a['triggered_at'][11:]} {a['alert_type']}：{a['rule_desc']}\n" for a in alerts)

    # 三、舆论焦点与观点矩阵
    s3 = "| 观点 | 情绪 | 条数 | 占比 | 代表言论 |\n|---|---|---|---|---|\n"
    for cl in clusters:
        q = cl["quotes"][0] if cl["quotes"] else None
        quote = f"「{q['text'][:28]}」[{q['id']}]" if q else "-"
        s3 += (f"| {cl['summary'].split('：')[0]} | {cl['emotion'] or cl['sentiment']} | {cl['count']} | "
               f"{cl['count'] * 100 / n if n else 0:.0f}% | {quote} |\n")
    emo = {}
    for c in contents:
        if c["emotion"]:
            emo[c["emotion"]] = emo.get(c["emotion"], 0) + 1
    s3 += "\n**负向情绪分布**：" + ("，".join(f"{k} {v} 条" for k, v in
                                     sorted(emo.items(), key=lambda kv: -kv[1])) or "无") + "。\n"

    # 四、风险研判结论（模板版，有 key 时由模型润色）
    b = ev["score_basis"]
    kol_ids = " ".join(f"[{k['id']}]" for k in keys) or "-"
    cl_ids = {cl["summary"].split("：")[0]: cl["representative_content_ids"] for cl in clusters}
    def ids(name):
        return " ".join(f"[{i}]" for i in cl_ids.get(name, [])[:2]) or "-"
    risk = (
        f"综合四因子评分，事件烈度指数 {ev['intensity_score']}，定为 **{ev['level']} 级**："
        f"扩散速度 {ev['score_speed']}/25（{b.get('speed', '')}），互动量 {ev['score_interaction']}/25"
        f"（{b.get('interaction', '')}），KOL 权重 {ev['score_kol']}/25（{b.get('kol', '')}），"
        f"敏感词 {ev['score_sensitive']}/25（{b.get('sensitive', '')}）。\n\n"
        f"- **品牌影响**：负面率 {neg * 100 / n if n else 0:.0f}%，出现明显的信任流失言论 {ids('品牌信任受损')}，"
        f"头部账号参与放大 {kol_ids}，对品牌美誉度冲击大。\n"
        f"- **法务风险**：已出现集中退款、赔偿诉求 {ids('退款赔偿诉求')} 和监管介入呼声 {ids('要求监管介入')}，"
        f"存在被投诉、行政检查的风险。\n"
        f"- **经营影响**：涉事门店需停业整改，食品安全担忧 {ids('食品安全担忧')} 可能波及其他门店客流与外卖订单。\n"
    )

    # 五、应对与处置建议
    advice = (
        "- **官方口径**：承认问题、致歉、公布整改与退款安排，不辩解、不甩锅；口径统一由品牌官方账号发布。\n"
        f"- **平息策略**：优先回应退款诉求与食品安全担忧两类核心关切；主动联系首发账号 [{first['id'] if first else '-'}] "
        f"与头部转发账号 {kol_ids} 说明整改进展；邀请第三方检测并公开结果。\n"
        "- **后续监测重点**：其他门店是否出现类似爆料；监管部门通报口径；退款兑现情况的二次舆情；"
        "静默期结束后负向声量是否反弹。\n"
    )
    if adopted:
        advice += "\n**已采纳的公关话术草案**：\n\n" + adopted["content"] + "\n"

    risk, advice, gen_mode, model_name = agent.report_narrative(conn, event_id, risk, advice, cfg)

    sections = [
        {"title": "一、事件基本信息", "body": s1},
        {"title": "二、传播态势分析", "body": s2},
        {"title": "三、舆论焦点与观点矩阵", "body": s3},
        {"title": "四、风险研判结论", "body": risk},
        {"title": "五、应对与处置建议", "body": advice},
    ]
    disposal_log = [{"time": d["created_at"], "from": d["from_status"], "to": d["to_status"],
                     "operator": d["operator"], "role": d["role"], "note": d["note"]} for d in disposals]
    return {"title": f"{ev['title']} 专项研判报告", "sections": sections,
            "disposal_log": disposal_log, "gen_mode": gen_mode, "model_name": model_name,
            "series": series}


def to_markdown(report):
    md = [f"# {report['title']}", "",
          f"> 生成方式：{report['gen_mode']}{'（' + report['model_name'] + '）' if report.get('model_name') else ''}"
          f" ｜ 生成时间：{report['created_at']} ｜ 数据为模拟数据", ""]
    for s in report["sections"]:
        md += [f"## {s['title']}", "", s["body"].strip(), ""]
    md += ["## 附表：处置记录", ""]
    if report["disposal_log"]:
        md += ["| 时间 | 状态变更 | 操作人 | 角色 | 批注 |", "|---|---|---|---|---|"]
        for d in report["disposal_log"]:
            md.append(f"| {d['time']} | {d['from'] or '-'} → {d['to']} | {d['operator']} | {d['role']} | {d['note'] or ''} |")
    else:
        md.append("暂无处置记录。")
    return "\n".join(md) + "\n"


# ---------- PDF ----------

def find_font():
    for p in FONT_CANDIDATES:
        if p.exists():
            return p
    return None


def _strip_md(s):
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
    return s.replace("`", "")


def to_pdf(report, series=None):
    from fpdf import FPDF
    font = find_font()
    if font is None:
        raise RuntimeError("找不到中文字体（simhei.ttf / msyh.ttc），无法导出 PDF")
    pdf = FPDF()
    pdf.set_auto_page_break(True, margin=15)
    pdf.add_font("cn", "", str(font))
    pdf.add_page()
    w = pdf.w - pdf.l_margin - pdf.r_margin

    pdf.set_font("cn", size=16)
    pdf.multi_cell(w, new_x="LMARGIN", new_y="NEXT", h=9, text=report["title"], align="C")
    pdf.set_font("cn", size=9)
    pdf.set_text_color(110, 110, 110)
    pdf.multi_cell(w, new_x="LMARGIN", new_y="NEXT", h=6, text=f"生成方式：{report['gen_mode']}　生成时间：{report['created_at']}　数据为模拟数据", align="C")
    pdf.set_text_color(0, 0, 0)

    for sec in report["sections"]:
        pdf.ln(3)
        pdf.set_font("cn", size=13)
        pdf.multi_cell(w, new_x="LMARGIN", new_y="NEXT", h=8, text=sec["title"])
        pdf.set_font("cn", size=10)
        if sec["title"].startswith("二") and series:
            _bar_chart(pdf, series, w)
        for line in sec["body"].strip().splitlines():
            line = line.rstrip()
            if not line:
                pdf.ln(2)
                continue
            if re.match(r"^\|[-| ]+\|$", line):
                continue
            if line.startswith("|"):
                cells = [c.strip() for c in line.strip("|").split("|")]
                line = "　".join(cells)
            line = re.sub(r"^#+\s*", "", line)
            pdf.multi_cell(w, new_x="LMARGIN", new_y="NEXT", h=6, text=_strip_md(line))

    pdf.ln(3)
    pdf.set_font("cn", size=13)
    pdf.multi_cell(w, new_x="LMARGIN", new_y="NEXT", h=8, text="附表：处置记录")
    pdf.set_font("cn", size=10)
    if report["disposal_log"]:
        for d in report["disposal_log"]:
            pdf.multi_cell(w, new_x="LMARGIN", new_y="NEXT", h=6, text=f"{d['time']}　{d['from'] or '-'} → {d['to']}　{d['operator']}（{d['role']}）　{d['note'] or ''}")
    else:
        pdf.multi_cell(w, new_x="LMARGIN", new_y="NEXT", h=6, text="暂无处置记录。")
    return bytes(pdf.output())


def _bar_chart(pdf, series, w):
    """在 PDF 里画各批次声量柱状图（灰 = 总量，红 = 负向）。"""
    top = max((s["total"] for s in series), default=0) or 1
    h, x0, y0 = 38, pdf.l_margin + 4, pdf.get_y() + 2
    bw = (w - 8) / len(series)
    pdf.set_draw_color(180, 180, 180)
    pdf.line(x0, y0 + h, x0 + w - 8, y0 + h)
    pdf.set_font("cn", size=7)
    for i, s in enumerate(series):
        x = x0 + i * bw + bw * 0.2
        th = h * s["total"] / top
        nh = h * s["negative"] / top
        pdf.set_fill_color(190, 200, 215)
        pdf.rect(x, y0 + h - th, bw * 0.3, th, style="F")
        pdf.set_fill_color(214, 69, 65)
        pdf.rect(x + bw * 0.3, y0 + h - nh, bw * 0.3, nh, style="F")
        pdf.set_xy(x - 2, y0 + h + 1)
        pdf.cell(bw * 0.6 + 4, 4, f"{s['label']} {s['total']}", align="C")
    pdf.set_xy(pdf.l_margin, y0 + h + 7)
    pdf.set_font("cn", size=8)
    pdf.set_text_color(110, 110, 110)
    pdf.multi_cell(w, new_x="LMARGIN", new_y="NEXT", h=5, text="图：各批次声量（浅色 = 总量，红色 = 负向）")
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("cn", size=10)
    pdf.ln(1)
