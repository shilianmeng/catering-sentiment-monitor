"""越秀区「双公示 · 行政处罚」采集：区政府门户的 JSON 接口，当事人是企业全名（带统一社会信用代码）。

和 gkmlpt 典型案例通报的区别：
- 一条 = 一份行政处罚决定书（文号唯一），不是一篇公告里拆出多起案件；
- 当事人没有脱敏，能对到真实品牌的营业执照主体，门店体检靠它；
- 字段是结构化的，不用从网页正文里猜主体和日期。

接口（2026-11-23 实测，见项目根目录《越秀区双公示_接口说明.md》）：
- 列表 /xyyxzl/credit/sgshzPunish/list?pageNum=&pageSize=&orderFields=cfJdrq&orderModels=desc
- 详情 /xyyxzl/credit/sgshzPunish/detail?sGuid=
  两个都要带 Accept: application/json + X-Requested-With + Referer，否则 406。

字段取舍：
- 处罚决定日期 cfJdrq 同时作 published_at 和 decided_at（双公示要求决定后 7 个工作日内公示，没有单独的发布日期）；
- 罚款金额从处罚内容 cfNr 的「作出如下处罚」之后的决定部分解析，**不用 cfNrFk**：
  实测 648 号决定写「罚款5000元」，cfNrFk 却是 1.0；
- 处罚内容里前面的「拟作出行政处罚」只是告知书复述，不当作决定。

礼貌采集：每个请求之间固定间隔（默认 3 秒），列表先按当事人名称筛出餐饮主体，只对这些取详情。
"""
import hashlib
import json
import re
import time
import urllib.parse
import urllib.request

from ..core.config import COLLECT_USER_AGENT
from . import gkmlpt, http, snapshot

SOURCE_ID = "yx_sgs"
SOURCE = {"id": SOURCE_ID, "name": "广州市越秀区人民政府（双公示·行政处罚）", "region": "广东省广州市越秀区",
          "base_url": "https://www.yuexiu.gov.cn", "sid": None, "kind": "sgs_api"}
PARSER_VERSION = 7   # v7：引号按语境判断（紧跟「没收」是物品名、前面有法条出处是引文）；v6：罚款摘要保留角分、只去掉引号里的法条（物品名引号保留）；v5：「罚没款金额合计」不当罚款、引号内法条的没收不算、「没收8袋……」实物没收要认；v4：决定起点不认裸「如下」、没收按决定实列（含「没收违法所得:15144元」）；v3：决定段落外的停业/吊销不算、罚没合计不当罚款；v2：大写金额「壹仟陆佰元整(￥1600)」、「罚款:5000元」

API = SOURCE["base_url"] + "/xyyxzl/credit/sgshzPunish"
HEADERS = {
    "User-Agent": COLLECT_USER_AGENT,
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": SOURCE["base_url"] + "/tzyx/xyyx/xygs/sgssj/sgsxzcf/index.html",
    "Accept-Language": "zh-CN,zh;q=0.9",
}
DEFAULT_DELAY = 3.0
MAX_CONSECUTIVE_ERRORS = 3

# 决定部分的起点：取最后一处，前面的「拟作出……处罚」是告知书复述
_DECISION_LEAD = re.compile(r"(?:作出|决定|给予)(?:如下|以下)[^：:。]{0,12}[：:]|处罚决定如下[：:]?|决定(?:对当事人)?(?:作出|给予)"
                            r"|(?:处罚|处理|具体)(?:如下|以下)[^：:。，,]{0,6}[：:]"   # 不认裸「如下」：564 号末尾「教育如下:」不是决定
                            r"|(?:给予|作出|作)[^：:。，,]{0,12}处罚\s*[：:]|[本我]局决定")
_CONFISCATE = re.compile(r"没收(?:当事人)?(违法所得|非法财物|违法生产经营的食品)?(?:违法所得)?\s*[:：]?\s*(?:人民币)?\s*([\d,，.]+)\s*(万)?元")
# 没收工具/食品等实物（非金额）：「没收8袋……」数量开头也算，只排除紧跟金额的「没收1516元」
_CONFISCATE_GOODS = re.compile(r"没收(?!(?:当事人)?违法所得)(?!(?:人民币)?\s*[\d,，.]+\s*万?元)[^，,。；;:：]{1,20}")
_QUOTED = re.compile(r"“([^”]*)”|\"([^\"]*)\"")
# 引号是法条引文还是物品名，先看引号外的语境，引号里的内容只作兜底：
# - 紧跟在「没收」后面（「没收“装饰金箔（规格：2g，数量：1瓶）”」）→ 物品名，留着，里面有标点也不删；
# - 前面同一句里有法条出处（「第一百二十四条“没收违法生产经营的食品”」「《食品安全法》规定：“……”」）→ 法条，去掉，再短也删；
# - 都没有，才看引号里像不像法条原文。
_GOODS_BEFORE_QUOTE = re.compile(r"没收(?:当事人)?(?:的|了)?\s*$")
_LAW_BEFORE_QUOTE = re.compile(r"第[一二三四五六七八九十百千零〇\d]+[条款项]|《[^》]{1,40}》|规定|法律|法规|条例|办法")
_LAW_QUOTE = re.compile(r"第[一二三四五六七八九十百零〇\d]+[条款项]|违反|规定|应当|不得|处[^，,。；;]{0,12}罚款|罚款|违法所得")


def _is_law_quote(text: str, m: re.Match) -> bool:
    before = re.split(r"[。；;]", text[max(0, m.start() - 60):m.start()])[-1]
    if _GOODS_BEFORE_QUOTE.search(before):
        return False
    if _LAW_BEFORE_QUOTE.search(before):
        return True
    return bool(_LAW_QUOTE.search(m.group(1) or m.group(2) or ""))


def _strip_law_quotes(text: str) -> str:
    return _QUOTED.sub(lambda m: "" if _is_law_quote(text, m) else m.group(0), text)


_SUSPEND = re.compile(r"吊销[^，。；;]{0,12}许可证|责令停产停业|责令停业")
_LAW_SUSPEND = re.compile(r"情节严重的?[，,]?[^。；;]{0,20}?(?:责令停产停业|责令停业)?[，,]?(?:直至|并可?|或者)?吊销[^，。；;]{0,12}许可证|情节严重的?[，,]?责令停产停业")
_CATERING_WFXW = "餐饮"

# 决定书常写大写金额：「罚款人民币壹仟陆佰壹拾元整(￥1610)」「处罚款人民币叁万伍仟元整(小写:35000元)」
# 「罚款人民币伍仟元整」（没附小写）。只认紧跟在「罚款」后面的金额，法条里「处五万元以上罚款」不碰。
_CN_DIGIT = {"零": 0, "〇": 0, "一": 1, "壹": 1, "二": 2, "贰": 2, "两": 2, "三": 3, "叁": 3, "四": 4, "肆": 4,
             "五": 5, "伍": 5, "六": 6, "陆": 6, "七": 7, "柒": 7, "八": 8, "捌": 8, "九": 9, "玖": 9}
_CN_UNIT = {"十": 10, "拾": 10, "百": 100, "佰": 100, "千": 1000, "仟": 1000}
_CN_NUM = "零〇一壹二贰两三叁四肆五伍六陆七柒八捌九玖十拾百佰千仟万萬"
_FINE_CN = re.compile(
    rf"(罚(?:没)?款)\s*[:：]?\s*(人民币)?\s*([{_CN_NUM}]+)\s*[?？]?\s*[元圆]整?"
    r"(?:\s*[(（]\s*(?:小写\s*[:：]?)?\s*[￥¥]?\s*([\d,，.]+)\s*元?\s*[)）])?")
_FINE_COLON = re.compile(r"(罚(?:没)?款)\s*[:：]\s*(?=(?:人民币)?\s*[\d,，.]+\s*万?元)")


def cn_amount(text: str) -> float | None:
    """大写/小写中文数字金额 → 数值（到万位；「壹拾肆万零伍佰」= 140500）。认不出返回 None。"""
    total, section, digit = 0, 0, None
    for ch in text:
        if ch in _CN_DIGIT:
            digit = _CN_DIGIT[ch]
        elif ch in _CN_UNIT:
            section += (1 if digit is None else digit) * _CN_UNIT[ch]
            digit = None
        elif ch in "万萬":
            total += (section + (digit or 0)) * 10000
            section, digit = 0, None
        else:
            return None
    v = total + section + (digit or 0)
    return float(v) if v else None


def normalize_amounts(text: str) -> str:
    """把决定部分里的大写罚款金额改写成阿拉伯数字，交给通用的 fine_breakdown。附了小写（￥）的以小写为准。"""
    def repl(m):
        small = gkmlpt._amount(m.group(4), None) if m.group(4) else None
        v = small if small else cn_amount(m.group(3))
        if not v:
            return m.group(0)
        return f"{m.group(1)}{m.group(2) or ''}{v:.2f}".rstrip("0").rstrip(".") + "元"
    return _FINE_COLON.sub(r"\1", _FINE_CN.sub(repl, text or ""))


def list_url(page: int, page_size: int = 20) -> str:
    q = {"pageNum": int(page), "pageSize": int(page_size), "orderFields": "cfJdrq", "orderModels": "desc"}
    return f"{API}/list?{urllib.parse.urlencode(q)}"


def detail_url(guid: str) -> str:
    return f"{API}/detail?{urllib.parse.urlencode({'sGuid': guid})}"


def _open(url: str, timeout: float):
    with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=timeout) as r:
        return r.status, r.read()


def default_fetch(url: str) -> http.Response:
    return http.fetch(url, opener=_open)


def parse_list(body: bytes) -> tuple[list[dict], int | None]:
    """返回 (本页条目, 总条数)。条目字段：guid / subject / doc_no / decided_at / categories。"""
    data = json.loads(body.decode("utf-8"))
    total = (data.get("page") or {}).get("total")
    out = []
    for x in data.get("datas") or []:
        if not x.get("sGuid") or not x.get("cfXdrMc"):
            continue
        out.append({"guid": x["sGuid"], "subject": x["cfXdrMc"].strip(), "doc_no": (x.get("cfWsh") or "").strip(),
                    "decided_at": (x.get("cfJdrq") or "")[:10] or None, "categories": x.get("cfCflb") or ""})
    return out, total


def name_is_catering(subject: str) -> bool:
    """列表阶段只有名称：按名称筛餐饮候选（宁多勿漏，详情里再按违法行为类型确认）。"""
    return any(w in subject for w in gkmlpt._CATERING_SUBJECT) or any(w in subject for w in ("美食", "食店", "小食"))


def parse_detail(body: bytes) -> dict:
    data = json.loads(body.decode("utf-8"))
    info = ((data.get("data") or {}).get("info")) or {}
    if not info.get("sGuid") or not info.get("cfXdrMc"):
        raise ValueError("详情接口没有返回 sGuid / cfXdrMc")
    return info


def decision_text(content: str) -> str:
    """处罚内容里真正的决定部分：最后一处「作出如下处罚：」「本局决定」之后；找不到就用全文。"""
    last = None
    for m in _DECISION_LEAD.finditer(content or ""):
        last = m
    return content[last.end():] if last else (content or "")


def has_decision_lead(content: str) -> bool:
    return bool(_DECISION_LEAD.search(content or ""))


def _money(v: float) -> str:
    return f"{gkmlpt.money_text(v)}元"


def handling_result(categories: str, content: str) -> tuple[str, float | None]:
    """(处理结果摘要, 罚款合计)。类别以官方 cfCflb 为准，金额从决定部分取。"""
    dec = normalize_amounts(decision_text(content))
    total, items = gkmlpt.fine_breakdown(dec)
    cats = [c.strip() for c in re.split(r"[;；,，]", categories or "") if c.strip()]   # 「其他-责令改正,罚款」
    parts = []
    for c in cats:
        if c == "罚款" and total:
            parts.append(gkmlpt._fine_label("罚款", total, items))
        elif c.startswith("没收"):
            # 以决定里实际列出的没收为准：类别「没收违法所得、没收非法财物」是合并标签，决定里不一定两样都有
            found = [f"没收{m.group(1) or ''}{_money(gkmlpt._amount(m.group(2), m.group(3)))}"
                     for m in _CONFISCATE.finditer(dec) if gkmlpt._amount(m.group(2), m.group(3))]
            if "非法财物" in c and not any("非法财物" in f for f in found) \
                    and _CONFISCATE_GOODS.search(_strip_law_quotes(dec)):
                found.append("没收非法财物")
            parts.append("、".join(dict.fromkeys(found)) if found else c)
        else:
            parts.append(c)
    if "罚款" not in cats and total:                         # 类别漏标但决定里写了罚款
        parts.append(gkmlpt._fine_label("罚款", total, items))
    # 停业/吊销只认决定部分里的；法条复述「情节严重的，责令停产停业，直至吊销许可证」不算本案处罚，
    # 找不到决定部分时也不从全文里猜
    dec_clean = _LAW_SUSPEND.sub("", dec)
    if has_decision_lead(content) and _SUSPEND.search(dec_clean) and not any(_SUSPEND.search(p) for p in parts):
        parts.append(_SUSPEND.search(dec_clean).group(0))
    if re.search(r"责令(?:当事人)?(?:改正|限期改正)", content or "") and not any("责令" in p for p in parts):
        parts.insert(0, "责令改正")
    return "；".join(parts) or "已作出行政处罚", total


def is_catering(info: dict) -> bool:
    return _CATERING_WFXW in (info.get("cfWfxw") or "") or name_is_catering(info.get("cfXdrMc") or "")


def record_key(guid: str) -> str:
    """一份决定书一条记录，按接口主键 sGuid。"""
    return hashlib.sha256(f"{SOURCE_ID}|{guid}".encode("utf-8")).hexdigest()


_HASH_FIELDS = ("cfXdrMc", "cfXdrShxym", "cfWsh", "cfJdrq", "cfCflb", "cfWfxw", "cfSy", "cfNr", "cfYj", "cfCfjg")


def content_hash(info: dict) -> str:
    """决定书内容的 hash：官方更正了事实、内容、金额，就算改稿。"""
    return hashlib.sha256(json.dumps([info.get(k) or "" for k in _HASH_FIELDS], ensure_ascii=False)
                          .encode("utf-8")).hexdigest()


def build_record(info: dict, snapshot_sha: str | None, fetched_at: str) -> dict:
    result, fine = handling_result(info.get("cfCflb"), info.get("cfNr"))
    laws = list(dict.fromkeys(gkmlpt._LAW.findall(f"{info.get('cfNr') or ''}{info.get('cfYj') or ''}")))
    subject = info["cfXdrMc"].strip()
    doc_no = (info.get("cfWsh") or "").strip()
    credit = (info.get("cfXdrShxym") or "").strip()
    day = (info.get("cfJdrq") or "")[:10] or None
    return {
        "record_key": record_key(info["sGuid"]), "content_hash": content_hash(info),
        "source_id": SOURCE_ID, "source_name": info.get("cfCfjg") or SOURCE["name"],
        "source_category": "官方通报", "official_url": detail_url(info["sGuid"]),
        "article_title": "越秀区双公示·行政处罚" + (f"（统一社会信用代码 {credit}）" if credit else ""),
        "doc_no": doc_no or None, "case_no": 1,
        "case_title": f"{subject} {doc_no}".strip(), "subject": subject,
        "enforcement_dept": info.get("cfCfjg") or None, "region": SOURCE["region"],
        "published_at": day, "decided_at": day,
        "violation": info.get("cfSy") or "", "legal_basis": laws, "regulation_text": info.get("cfYj") or None,
        "investigation_status": "已处罚", "handling_result": result, "fine_amount": fine,
        "is_catering": 1 if is_catering(info) else 0,
        "snapshot_sha256": snapshot_sha, "parser_version": PARSER_VERSION, "fetched_at": fetched_at,
    }


def collect(conn, *, max_pages: int = 1, page_size: int = 20, since: str | None = None,
            catering_only: bool = True, max_details: int | None = None, guids: list[str] | None = None,
            delay: float = DEFAULT_DELAY, fetch=None, sleep=time.sleep, snapshot_root=None) -> dict:
    """列表（按决定日期倒序）→ 按名称筛餐饮 → 取详情 → 快照 → 入库 → 关联门店。

    since：只要这天及以后的决定，翻到更早的就停；max_details：本次最多取几份详情（试跑用）；
    guids：跳过列表直接取这几份详情（补抓、复现用）。每个请求之间 sleep(delay)。
    """
    from . import pipeline                                   # 避免循环导入
    fetch = fetch or default_fetch
    stats = {"source_id": SOURCE_ID, "source_name": SOURCE["name"], "pages": 0, "listed": 0, "total": None,
             "candidates": 0, "details": 0, "catering": 0,
             "inserted": 0, "revised": 0, "unchanged": 0, "reparsed": 0, "errors": []}
    requests = 0

    def get(url):
        nonlocal requests
        if requests:
            sleep(delay)
        requests += 1
        return fetch(url)

    if guids:
        todo = [{"guid": g} for g in guids]
    else:
        todo, stop = [], False
        for page in range(1, max_pages + 1):
            url = list_url(page, page_size)
            try:
                items, total = parse_list(get(url).body)
            except (http.FetchError, ValueError) as e:
                stats["errors"].append({"url": url, "error": str(e)})
                break
            stats["pages"] += 1
            stats["total"] = total
            if not items:
                break
            for it in items:
                if since and it["decided_at"] and it["decided_at"] < since:
                    stop = True
                    break
                stats["listed"] += 1
                if not catering_only or name_is_catering(it["subject"]):
                    todo.append(it)
            if stop:
                break
            if total is not None and page * page_size >= total:   # 越界页接口会重复返回最后一页，到底就停
                break
    if max_details is not None:
        todo = todo[:max_details]
    stats["candidates"] = len(todo)

    consecutive_errors = 0
    for it in todo:
        url = detail_url(it["guid"])
        try:
            resp = get(url)
            info = parse_detail(resp.body)
        except (http.FetchError, ValueError) as e:
            stats["errors"].append({"url": url, "error": str(e)})
            consecutive_errors += 1
            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:      # 疑似被风控，立即停手
                stats["aborted"] = f"连续 {consecutive_errors} 次详情失败，已停止"
                break
            continue
        consecutive_errors = 0
        sha = snapshot.save(conn, url, SOURCE_ID, resp.body, resp.status, snapshot_root)
        rec = build_record(info, sha, pipeline._now())
        stats["details"] += 1
        stats["catering"] += rec["is_catering"]
        stats[pipeline.upsert_record(conn, rec)] += 1
        conn.commit()                                        # 逐条提交，中途停下也不丢已采的
    stats["requests"] = requests
    stats["linked"] = pipeline.link_records(conn)
    conn.commit()
    return stats


def reparse_one(conn, url: str, sha: str, snapshot_root=None) -> str | None:
    """用已存的详情快照按当前规则重新解析入库；快照缺失返回 None。"""
    from . import pipeline
    body = snapshot.load(sha, snapshot_root)
    if body is None:
        return None
    return pipeline.upsert_record(conn, build_record(parse_detail(body), sha, pipeline._now()), reparse=True)
