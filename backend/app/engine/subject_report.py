"""第④步·主体体检报告：把一个营业执照主体的官方处罚、风险分、区内位置写成一份可导出的报告（Markdown / PDF）。

纯函数，只吃 subject_risk 算好的结果，不查库、不调模型：每句话都能回指到某份处罚决定书。
- 分数、档位、衰减全部来自 subject_risk.score_subject，报告不另算分；
- 「区内位置」来自同一批数据的排名，和 /subjects/risk 接口一致；
- 连锁示例（可选）只列事实，不和本主体比分——单店和连锁门店不是一个口径；
- 没有投诉分，报告里明写原因，不编数据。
"""
import re

from . import store_risk as sr
from . import subject_risk as sj

_SNIPPET = 160


def _money(v) -> str:
    if not v:
        return "—"
    v = round(v, 2)
    return (f"{v:,.0f}" if v == int(v) else f"{v:,.2f}") + " 元"     # 不用 ¥：黑体没有这个字形，PDF 里会缺字


def _snippet(text: str | None, n: int = _SNIPPET) -> str:
    s = re.sub(r"\s+", "", text or "")
    s = re.sub(r"(《[^》]+》)\1+", r"\1", s)    # 原文常把法名连写几遍
    return s if len(s) <= n else s[:n] + "……"


def _cell(s) -> str:
    return str(s if s not in (None, "") else "—").replace("|", "／").replace("\n", " ")


def _advice(detail: dict) -> list[str]:
    """整改建议：只按命中的违法类别和档位给通用合规提示，不对个案下结论。"""
    cats = detail["categories"]
    tips = []
    if sj.CAT_FOOD in cats:
        tips.append("食品安全：核对《食品经营许可证》的主体业态、经营项目与实际经营是否一致，到期前办理延续。")
    if sj.CAT_FIRE in cats:
        tips.append("消防安全：公众聚集场所营业前须取得消防安全检查意见书；装修改造后按规定办理验收或备案。")
    if sj.CAT_LICENSE in cats:
        tips.append("登记/证照：营业执照登记事项（地址、经营范围）变更后及时办理变更登记。")
    if sj.CAT_CITY in cats:
        tips.append("市容/占道：门前不出店经营、不占道摆放，招牌和外墙设置按街道要求报备。")
    if sj.CAT_TOBACCO in cats:
        tips.append("烟草专卖：零售卷烟须持烟草专卖零售许可证，并从当地烟草公司进货。")
    if any("停业" in (r["handling_result"] or "") or "吊销" in (r["handling_result"] or "")
           for r in detail["records"]):
        tips.append("曾被责令停业/吊销：复业前保留整改完成的书面材料，便于复查。")
    if detail["record_count"] >= 2:
        tips.append("多次被处罚：建议建立证照到期和检查整改台账，由专人跟进。")
    return tips or ["无命中类别，保持现有合规管理。"]


def build(detail: dict, records: list[dict], district: dict, chain: list[dict] | None = None) -> dict:
    """detail = subject_risk.score_subject 的结果；records = 该主体原始记录（带违法事实、处罚依据）；
    district = 同批数据的 {rank, total, category_rank, category_total, level_counts}；chain = 连锁示例的记录。"""
    raw = {r.get("id"): r for r in records}
    title = f"{detail['subject']} 合规体检报告"
    lv = detail["level"]

    # 一、结论
    cats = "、".join(f"{k} {v} 次" for k, v in detail["categories"].items())
    summary = [
        f"- **风险等级：{lv}（{detail['score']} 分 / 满分 {sr.OFFICIAL_CAP}）**，"
        f"越秀区 {district['total']} 个餐饮主体中排第 **{district['rank']}** 名。",
        f"- {detail['first_at']} 至 {detail['last_at']} 共被行政处罚 **{detail['record_count']}** 次（{cats}），"
        f"累计罚款 **{_money(detail['fine_total'])}**，最重档位：{detail['worst_tier']}。",
    ]
    if district.get("category_rank"):
        summary.append(f"- 只看食品安全：区内 {district['category_total']} 个被罚主体中排第 "
                       f"**{district['category_rank']}** 名。")
    summary.append(f"- 投诉分：{detail['complaint_note']}。")

    # 二、主体信息
    info = [
        "| 项目 | 内容 |", "|---|---|",
        f"| 主体名称 | {_cell(detail['subject'])} |",
        f"| 统一社会信用代码 | {_cell(detail['credit_code'])} |",
        f"| 曾用名 | {_cell('、'.join(detail['former_names']))} |",
        f"| 数据来源 | 越秀区政府「双公示」行政处罚公示（官方公开） |",
    ]

    # 三、处罚记录（按时间）
    recs = sorted(detail["records"], key=lambda x: str(x["published_at"] or ""))
    rows = ["| 决定日期 | 文号 | 处罚机关 | 类别 | 处理结果 |", "|---|---|---|---|---|"]
    facts = []
    for i, x in enumerate(recs, 1):
        rows.append(f"| {_cell(x['published_at'])} | {_cell(x['doc_no'])} | {_cell(x['enforcement_dept'])} | "
                    f"{_cell(x['category'])} | {_cell(x['handling_result'])} |")
        r = raw.get(x["id"], {})
        facts += [f"**{i}. {x['doc_no']}**", "",
                  f"- 违法事实：{_snippet(r.get('violation'))}",
                  f"- 处罚依据：{_snippet(r.get('regulation_text'), 120)}",
                  f"- 原文：{x['official_url']}", ""]

    # 四、评分拆解
    score = ["| 文号 | 档位 | 基础分 | 加分理由 | 时间衰减 | 得分 |", "|---|---|---|---|---|---|"]
    for x in detail["records"]:
        score.append(f"| {_cell(x['doc_no'])} | {x['tier']} | {x['base']} | {_cell(x['reason'])} | "
                     f"×{x['decay']} | {x['points']} |")
    score += ["", f"合计 {detail['official_raw']} 分，封顶 {sr.OFFICIAL_CAP} → **{detail['score']} 分**。",
              f"规则：罚没起步 {sr.TIER_BASE[sr.TIER_FINE]} 分，罚款 ≥1000 元按对数加分（最多 +{sr.FINE_BONUS_CAP}），"
              f"停业/吊销 +{sr.SUSPEND_BONUS}；每过 {sr.OFFICIAL_HALF_LIFE_DAYS} 天分值减半。"
              f"等级：≥{sr.LEVEL_HIGH} 高，≥{sr.LEVEL_MID} 中。"]

    sections = [
        {"title": "一、体检结论", "body": "\n".join(summary)},
        {"title": "二、主体信息", "body": "\n".join(info)},
        {"title": "三、处罚记录", "body": "\n".join(rows + [""] + facts)},
        {"title": "四、评分拆解", "body": "\n".join(score)},
        {"title": "五、整改建议", "body": "\n".join(f"- {t}" for t in _advice(detail))},
    ]
    if chain:
        lines = ["同一连锁品牌在越秀被处罚的门店。各门店是独立登记的分支机构，统一社会信用代码各不相同，下表逐家列出；只列事实，不与上文主体比分。", "",
                 "| 门店 | 统一社会信用代码 | 决定日期 | 文号 | 类别 | 处理结果 |", "|---|---|---|---|---|---|"]
        for c in sorted(chain, key=lambda c: str(c.get("published_at") or "")):
            lines.append(f"| {_cell(c.get('subject'))} | {_cell(c.get('credit_code'))} | {_cell(c.get('published_at'))} | {_cell(c.get('doc_no'))} | "
                         f"{_cell(c.get('category') or sj.classify(c))} | {_cell(c.get('handling_result'))} |")
        sections.append({"title": "附：连锁品牌示例", "body": "\n".join(lines)})
    sections.append({"title": "说明", "body": "\n".join([
        "- 全部内容来自官方公开的行政处罚决定，每条可按原文链接核对；报告不含投诉、评价等非官方信息。",
        "- 行政处罚记录反映的是历史违法事实及处理结果，不代表主体当前经营状况。",
        "- 风险分是按固定规则计算的参考值，不是监管部门的评价。",
    ])})
    return {"title": title, "subject_key": detail["subject_key"], "as_of": district.get("as_of"),
            "score": detail["score"], "level": lv, "sections": sections}


def to_markdown(report: dict) -> str:
    md = [f"# {report['title']}", "", f"> 统计截至 {report['as_of']} ｜ 数据来源：越秀区双公示（官方公开）", ""]
    for s in report["sections"]:
        md += [f"## {s['title']}", "", s["body"].strip(), ""]
    return "\n".join(md)


def to_pdf(report: dict) -> bytes:
    from fpdf import FPDF
    from .reporting import _strip_md, find_font
    font = find_font()
    if font is None:
        raise RuntimeError("找不到中文字体（simhei.ttf / msyh.ttc），无法导出 PDF")
    pdf = FPDF()
    pdf.set_auto_page_break(True, margin=15)
    pdf.add_font("cn", "", str(font))
    pdf.add_page()
    w = pdf.w - pdf.l_margin - pdf.r_margin

    def line(text, size=10, h=6, color=(0, 0, 0), align="L"):
        pdf.set_font("cn", size=size)
        pdf.set_text_color(*color)
        pdf.multi_cell(w, new_x="LMARGIN", new_y="NEXT", h=h, text=text, align=align)
        pdf.set_text_color(0, 0, 0)

    line(report["title"], 16, 9, align="C")
    line(f"统计截至 {report['as_of']}　数据来源：越秀区双公示（官方公开）", 9, color=(110, 110, 110), align="C")
    for sec in report["sections"]:
        pdf.ln(3)
        line(sec["title"], 13, 8)
        for raw in sec["body"].strip().splitlines():
            raw = raw.rstrip()
            if not raw:
                pdf.ln(2)
                continue
            if re.match(r"^\|[-| ]+\|$", raw):
                continue
            if raw.startswith("|"):
                raw = "　".join(c.strip() for c in raw.strip("|").split("|"))
            line(_strip_md(raw), 9 if sec["title"].startswith(("三", "四", "附")) else 10)
    return bytes(pdf.output())
