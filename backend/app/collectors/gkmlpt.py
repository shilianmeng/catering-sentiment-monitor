"""广东「政府信息公开目录平台」（gkmlpt）适配器。

广州、深圳等市场监管局的政务公开都跑在这套平台上：
- 列表：GET {base}/gkmlpt/api/all/0?page=N[&sid=站点号] → JSON {articles:[{title,url,date,...}]}
- 正文：静态 HTML，「发布机构/成文日期/文号/发布日期」在页头，正文在「浏览次数」之后。

典型案例公告一篇里有多起案件，标题写法有两种：
  广州  「一、刘某某使用伪造食品经营许可证案」+「案情：」
  深圳  「案例一：深圳市罗湖区××店涉嫌经营……案」（页面上「案例/三：」偶尔被拆成几行）
这里逐案拆开，每起案件抽出：当事人、办案单位、日期、法条、调查状态、处理结果、罚款金额。
解析只依赖文本，不依赖页面 class，改版时最多影响页头字段。
"""
import hashlib
import html as htmllib
import json
import re
from datetime import datetime, timedelta, timezone

CN_TZ = timezone(timedelta(hours=8))
CN_NUM = "一二三四五六七八九十"

# 标题同时含「食品/餐饮」和「案例/案件」才去抓正文
_TOPIC_WORDS = ("食品", "餐饮", "食安", "外卖", "校园食品")
_CASE_WORDS = ("案例", "案件", "典型")

_CASE_HEAD = re.compile(
    rf"^(?:案例\s*([{CN_NUM}]+)\s*[：:]\s*|([{CN_NUM}]+)\s*、\s*)(.{{4,80}}?案(?:件)?)\s*$")
# 案件正文到这些行为止：后面是点评、落款
_CASE_END = re.compile(r"^(?:（[一二三四五六七八九十]+）\s*)?(?:典型意义|案件剖析|案例评析|案例点评|警示)|^发布$|^主办单位")
# 公告末尾附的「相关规定」：只是法条原文（含「情节严重的，吊销许可证」这类可能的处罚），不是本案决定
_REG_HEAD = re.compile(r"^(?:【\s*相关(?:法律)?(?:规定|法条|法律法规)\s*】|(?:附[：:]?\s*)?相关(?:法律)?(?:规定|法条|法律法规)\s*[：:]?)\s*$")
# 案情里转述法条原文的句子：同样只说明「可能怎么罚」
_STATUTE_SENTENCE = re.compile(r"由县级以上|有下列情形之一|^第[一二三四五六七八九十百零\d]+条|规定[：:]"
                               r"|以上[^。；]{0,16}以下(?:的)?罚款|(?:可以|可)并?处")
# 条件性罚则：「情节严重的，吊销……」「逾期不改正的，处……」只说明可能后果，不是本案决定
# 已认定的事实不算：「属于情节严重的情形」「构成拒不改正的行为」是本案认定，后面跟的是实际决定
# 「情节严重的当事人」只是修饰语，后面跟的是本案实际决定；条件句的「……的」后面紧跟逗号或罚则动词
# 「如/若/如果属于情节严重的，……」带假设词的，即使有「属于」也仍是条件句
_COND_CORE = r"(?:情节严重|情节恶劣|拒不改正|逾期不改正?|拒不执行|造成严重后果|再次违反|屡次违反)的"
_COND_NEXT = r"(?=\s*[，,]|\s*(?:处|并处|可以|可|责令|吊销|没收|给予|予以|依法|从重))"
_CONDITIONAL = re.compile(rf"(?<!属于)(?<!构成)(?<!认定为){_COND_CORE}{_COND_NEXT}"
                          rf"|(?:如果|倘若|假如|如|若|一旦)[^，,。；;]{{0,8}}?{_COND_CORE}")
# 拟处罚（处罚告知阶段）：还不是最终决定
_PROPOSED = re.compile(r"拟[^。；]{0,30}?(?:罚款|处罚|吊销|停业|警告|没收)")
# 「拟作出以下行政处罚：一、警告；二、罚款5000元」：冒号后面列的各项都在「拟」的范围里，分号拆开后也是
_PROPOSAL_LEAD = re.compile(r"拟[^。；;：:]{0,40}?(?:处罚|处理|决定)[^。；;：:]{0,6}[：:]")
# 列表中途出现的实际决定（「……该局决定罚款5000元」）结束「拟」的范围。
# 「决定书」「以……决定为准」只是提到文书，不是决定；括号里的说明也不算
_FINAL_DECISION = re.compile(r"(?<![拟原])(?:决定(?!书|为准)|已作出|已对)")
_PAREN = re.compile(r"（[^（）]*）|\([^()]*\)")
# 分行列出的拟处罚各项：「一、给予警告」「（二）罚款」「2.没收」，上一行没有标点也接着算
_LIST_ITEM = re.compile(rf"^(?:[{CN_NUM}]+\s*[、.．]|[（(][{CN_NUM}\d]+[）)]|\d+\s*[、.．)）])")
_PENALTY_WORD = re.compile(r"罚款|处罚|吊销|停业|停产|警告|没收|责令")
# 解析规则版本：规则改了就加 1。同一份快照，版本更新的解析结果才能覆盖旧的
PARSER_VERSION = 8   # 「罚没款合计」不当罚款合计（2026-11-23）：已核对 54 篇种子快照解析结果零变化，不升版本
# 处理日期只取「实际决定」分句里写明的日期：抽检、检查、收到线索的日期不是处理日期
_DECISION_EVENT = re.compile(r"作出|决定|给予|责令|移送公安|移交公安|立案侦查|开具|处以|并处")
# 日期和决定动词之间出现这些词，说明这个日期属于检查、抽检、违法行为本身
_NON_DECISION_EVENT = re.compile(r"执法人员|检查|抽检|抽样|检验|检测|发现|巡查|收到|线索|使用|购进|期间")
# 「2023年4月10日前改正」「2022年4月6日至……」「2023年9月起」：期限或区间，不是决定日期
# 「该局当场责令改正，并给予警告」：当场决定，日期就是本案里它前面最近的检查日期
_ON_SPOT_DECISION = re.compile(r"当场(?:责令|给予|作出|处以|处罚|警告|开具|没收)")
# 当场决定只认检查事件的日期；生产日期、保质期、整改期限、收到举报的日期都不是
_INSPECTION_EVENT = re.compile(r"检查|巡查|抽查|核查|现场|执法人员|突击|暗访")
_DATE_ATTRIBUTE_BEFORE = re.compile(r"(?:生产|出厂|保质|到期|有效|限用|加工|包装)(?:日期|期)?(?:为|是|至|：|:)?\s*$"
                                    r"|期限(?:为|是|至|：|:)?\s*$|日期(?:为|是|：|:)\s*$|当事人于\s*$")
_DATE_NOT_DECISION_AFTER = re.compile(r"^\s*(?:前|之前|以前|起|至|到|期间|止)")
# 只是复述前面已经写过的罚款（「已缴纳罚款5000元」「上述罚款」），不是另一笔
_FINE_REFERENCE = re.compile(r"缴纳|缴清|缴款|上述罚款|该笔|前述罚款|已执行")
_FINE_TOTAL = re.compile(r"(?:合计|共计|总计|共)(?:处以|处|罚没款?|罚款)?(?:人民币)?\s*[\d,，.]+\s*万?元")
# 正文开头的小标题，去掉
_CASE_LEAD = re.compile(r"^(?:（[一二三四五六七八九十]+）\s*)?(?:案情(?:简介|介绍)?|基本案情)\s*[：:]?\s*")
# 「某区市场监管局查处某店……案」：前半是办案单位，后半才是当事人
_TITLE_DEPT = re.compile(r"^(.{2,24}?(?:市场监督管理局|市场监管局|综合行政执法局|监管局))查处(.+)$")
_SUBJECT_SUFFIX = re.compile(
    r"^(.{2,40}?(?:店|公司|酒楼|餐厅|饭店|餐馆|食堂|档口|摊档|大排档|作坊|团伙|商行|超市|中心|工作室|"
    r"经营部|个体户|私厨馆|馆|屋|幼儿园|学校|中学|小学))")
_VERBS = "涉嫌|使用|经营|生产|销售|从事|未取得|未主动|未按|违规|擅自|非法|发布|利用|超范围"
_SUBJECT_VERB = re.compile(rf"^(.{{1,30}}?)(?:{_VERBS})")
# 「某某有限公司海珠宝岗店未主动……」：当事人是公司下面那家门店
_BRANCH = re.compile(rf"^([一-龥（）()]{{2,10}}?店)(?={_VERBS})")
# 「某某有限公司悠方分公司设置……」：分公司是独立登记的经营主体，不能截成总公司（否则会挂到总店）
_BRANCH_CO = re.compile(r"^([一-龥（）()]{1,12}?分公司)")
_DEPT = re.compile(r"([一-龥]{2,16}?(?:市场监管局|监督管理局[一-龥]{2,4}监管局|监管局))")
_DATE = re.compile(r"(\d{4})年(\d{1,2})月(?:(\d{1,2})日)?")
_FINE = re.compile(r"罚款(?:人民币)?\s*([\d,，.]+)\s*(万)?元|处(?:以)?(?:人民币)?\s*([\d,，.]+)\s*(万)?元(?:的)?罚款")
_LAW = re.compile(r"《[^》]{2,40}》第[^，。；、《]{1,12}?条(?:第[^，。；、《]{1,6}?[款项])*")
# 「移送公安机关立案侦查」只是移送，不算公安已立案；要「公安机关已/对……立案侦查」或「正在侦办」
_POLICE_FILED = re.compile(r"公安机关(?:已对|已|对)[^。]{0,16}?立案侦查|公安机关已立案|抓获犯罪嫌疑人|正在(?:进一步)?侦办")
_TO_POLICE = re.compile(r"(?:移送|移交)公安")
_QUOTED_SHOP = re.compile(r"[“\"]([^”\"]{2,30}(?:店|餐厅|酒楼|饭店)[^”\"]{0,10})[”\"]")

_CATERING_SUBJECT = ("餐饮", "饭店", "餐厅", "餐馆", "酒楼", "食堂", "外卖", "小吃", "面馆", "面店", "粉店",
                     "汤粉", "火烧店", "凉茶店", "烧鸡", "快餐", "茶餐厅", "饮品店", "奶茶", "大排档",
                     "私厨", "美食店", "麻辣烫", "料理")
_CATERING_BODY = ("后厨", "菜品", "堂食", "网络餐饮", "就餐", "餐饮服务", "外卖平台", "供餐", "点餐")
# 行政处罚的几种写法：作出……行政处罚 / 处以罚款 / 罚款 N 元 / 给予警告 / 依……规定处罚
_PENALIZED = re.compile(r"作出[^。]{0,40}行政处罚|处以罚款|罚款\s*[\d]|给予警告|规定(?:予以)?处罚|依法处罚")


def list_url(source: dict, page: int) -> str:
    url = f"{source['base_url'].rstrip('/')}/gkmlpt/api/all/0?page={int(page)}"
    return url + (f"&sid={source['sid']}" if source.get("sid") else "")


def _day(ts) -> str | None:
    try:
        return datetime.fromtimestamp(int(ts), CN_TZ).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError):
        return None


def parse_list(body: bytes) -> list[dict]:
    data = json.loads(body.decode("utf-8"))
    out = []
    for a in data.get("articles") or []:
        if not a.get("url") or not a.get("title"):
            continue
        out.append({"id": a.get("id"), "title": a["title"].strip(), "url": a["url"],
                    "published_at": _day(a.get("date") or a.get("first_publish_time")),
                    "doc_no": (a.get("document_number") or "").strip() or None})
    return out


def is_candidate(title: str) -> bool:
    return any(w in title for w in _TOPIC_WORDS) and any(w in title for w in _CASE_WORDS)


def html_to_lines(body: bytes) -> list[str]:
    s = body.decode("utf-8", errors="replace")
    s = re.sub(r"<(script|style)\b.*?</\1>", "", s, flags=re.S | re.I)
    s = re.sub(r"<!--.*?-->", "", s, flags=re.S)
    s = re.sub(r"<br\s*/?>|</p>|</div>|</h\d>|</li>|</tr>", "\n", s, flags=re.I)
    s = htmllib.unescape(re.sub(r"<[^>]+>", "\n", s)).replace("　", " ").replace("\xa0", " ")
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in s.splitlines()]
    lines = [ln for ln in lines if ln]
    # 深圳页面偶尔把「案例三：」拆成「案例」「三：」两三行，先拼回去
    merged, i = [], 0
    while i < len(lines):
        ln = lines[i]
        if ln == "案例" and i + 1 < len(lines) and re.fullmatch(rf"[{CN_NUM}]+\s*[：:]?", lines[i + 1]):
            nxt = lines[i + 1].rstrip("：:")
            ln, i = f"案例{nxt}：", i + 2
            if i < len(lines) and not _CASE_HEAD.match(ln):
                ln, i = ln + lines[i], i + 1
            merged.append(ln)
            continue
        # 广州有的页面把「八、黄埔区市场」「监督管理」「局查处……案」拆成几行；拼起来像案件标题才拼
        if re.match(rf"^[{CN_NUM}]+\s*(?:、|$)", ln) and not _CASE_HEAD.match(ln) and len(ln) <= 20:
            joined = ln
            for k in range(i + 1, min(i + 9, len(lines))):
                joined += lines[k]
                if _CASE_HEAD.match(joined):
                    merged.append(joined)
                    i = k + 1
                    break
                if len(lines[k]) > 20:
                    break
            else:
                joined = None
            if joined is not None and merged and merged[-1] == joined:
                continue
        merged.append(ln)
        i += 1
    return merged


def _meta(lines: list[str], label: str) -> str | None:
    for i, ln in enumerate(lines):
        if ln.startswith(label + "："):
            rest = ln[len(label) + 1:].strip()
            if rest:
                return rest
            if i + 1 < len(lines) and not re.match(r"^[一-龥]{2,5}：", lines[i + 1]):
                return lines[i + 1].strip()
            return None
    return None


def _body_lines(lines: list[str]) -> list[str]:
    start = next((i for i, ln in enumerate(lines) if ln.startswith("发布日期：") and "浏览" in ln), None)
    if start is None:
        start = next((i for i, ln in enumerate(lines) if "浏览次数" in ln), 0)
    return lines[start + 1:]


def _norm_date(y, m, d) -> str:
    return f"{int(y):04d}-{int(m):02d}" + (f"-{int(d):02d}" if d else "")


def split_title(case_title: str) -> tuple[str | None, str]:
    """「某区市场监管局查处某店……案」→ (办案单位, 「某店……案」)；没有这种前缀返回 (None, 原标题)。"""
    title = re.sub(r"^(?:案例[一二三四五六七八九十]+[：:])", "", case_title).strip()
    m = _TITLE_DEPT.match(title)
    return (m.group(1), m.group(2).strip()) if m else (None, title)


def subject_of(case_title: str, text: str = "") -> str:
    _, title = split_title(case_title)
    m = _SUBJECT_SUFFIX.match(title)
    # 「某餐饮店」「某公司」直接取；「李某经营无证餐饮店」这种动词在前的，当事人是「李某」
    if m and not _SUBJECT_VERB.match(m.group(1)[:-1]):
        subject = m.group(1)
        if subject.endswith(("公司", "商行")):
            rest = title[len(subject):]
            branch = (_BRANCH_CO.match(rest) if subject.endswith("公司") else None) or _BRANCH.match(rest)
            if branch:
                subject += branch.group(1)
        return subject
    m = _SUBJECT_VERB.match(title)
    if m:
        return m.group(1)
    return title[:-1] if title.endswith("案") else title


def shop_names(text: str) -> list[str]:
    return list(dict.fromkeys(_QUOTED_SHOP.findall(text)))


def investigation_status(text: str) -> str:
    if _POLICE_FILED.search(text):
        return "公安已立案"
    if _TO_POLICE.search(text):
        return "已移送公安"
    if _PENALIZED.search(text):
        return "已处罚"
    if "责令" in text:
        return "责令改正"
    if "立案" in text:
        return "已立案"
    return "已通报"


def fines(text: str) -> list[float]:
    out = []
    for m in _FINE.finditer(text):
        num, wan = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        try:
            v = float(num.replace(",", "").replace("，", ""))
        except ValueError:
            continue
        out.append(v * 10000 if wan else v)
    return out


def _amount(num: str, wan: str | None) -> float | None:
    try:
        v = float(num.replace(",", "").replace("，", ""))
    except ValueError:
        return None
    return v * 10000 if wan else v


def fine_breakdown(text: str) -> tuple[float | None, list[float]]:
    """罚款合计和各笔明细。一起案件可能对不同违法行为分别罚款（70000 + 5000），要相加而不是取最大；
    复述已罚金额的分句（「已缴纳罚款」「上述罚款」）不重复计；公告自己写了「合计/共计」的以它为准。"""
    items, total = [], None
    for c in re.split(r"(?<=[。；;\n])", text):
        m_total = _FINE_TOTAL.search(c)
        if m_total:
            # 「罚没款合计」= 罚款 + 没收，不是罚款本身：只从分句里去掉，不当罚款合计
            # 「罚没款合计」「罚没款金额合计」「罚没合计」都算；「罚没」可能在「合计」前面隔着几个字
            is_confiscation_sum = bool(re.search(r"罚没[^。；;，,\d]{0,6}$", c[:m_total.start()])) \
                or "罚没" in m_total.group(0)
            num = re.search(r"([\d,，.]+)\s*(万)?元", m_total.group(0))
            if num and not is_confiscation_sum:
                total = _amount(num.group(1), num.group(2))
            c = c[:m_total.start()] + c[m_total.end():]
        if _FINE_REFERENCE.search(c):
            continue
        items.extend(dict.fromkeys(fines(c)))          # 同一分句里重复写的同一金额只算一次
    if total is None and items:
        total = sum(items)
    return total, items


def money_text(v: float) -> str:
    """金额文本：整数不带小数，有角分的保留两位（46,667.19 不能写成 46,667）。"""
    v = round(v, 2)
    return f"{v:,.0f}" if v == int(v) else f"{v:,.2f}"


def _fine_label(prefix: str, total: float, items: list[float]) -> str:
    if len(items) > 1 and abs(sum(items) - total) < 0.01:
        return f"{prefix}{money_text(total)}元（{'+'.join(money_text(v) for v in items)}）"
    return f"{prefix}{money_text(total)}元"


def _is_inspection_date(text: str, m: re.Match, later: list) -> bool:
    """这个日期是不是检查事件的日期：日期本身不是某个属性的值（生产日期为/保质期至/期限为/收到举报），
    并且它所在分句（到句号或下一个日期为止）里写了检查动作。"""
    lead = text[max(0, m.start() - 8):m.start()]
    if _DATE_ATTRIBUTE_BEFORE.search(lead) or _DATE_NOT_DECISION_AFTER.match(text[m.end():m.end() + 4]):
        return False
    end = later[0].start() if later else len(text)
    clause = re.split(r"[。；;\n]", text[m.end():end], maxsplit=1)[0]
    return bool(_INSPECTION_EVENT.search(lead[-3:] + clause))


def decided_date(text: str) -> str | None:
    """处理日期：明确写在决定行为上的日期，取最近的一个——
    「2025年1月13日，越秀区市场监管局对……作出……行政处罚」「……局于2023年12月6日对当事人开具《当场处罚决定书》」。
    「当场责令改正/给予警告」的，取本案里它前面最近的检查日期（当场即检查当天）。
    抽检、检查、违法发生、整改期限的日期本身都不是处理日期；找不到就留空，不拿发布日期或正文最大日期充数。"""
    found = []
    for m in _DATE.finditer(text):
        after = re.split(r"[。；;\n]", text[m.end():m.end() + 100], maxsplit=1)[0]
        if _DATE_NOT_DECISION_AFTER.match(after) or re.search(r"当事人于\s*$", text[max(0, m.start() - 6):m.start()]):
            continue
        verb = _DECISION_EVENT.search(after)
        if verb and not _NON_DECISION_EVENT.search(after[:verb.start()]):
            found.append(_norm_date(*m.groups()))
    for spot in _ON_SPOT_DECISION.finditer(text):
        dates = list(_DATE.finditer(text, 0, spot.start()))
        inspections = [m for i, m in enumerate(dates) if m.group(3) and _is_inspection_date(text, m, dates[i + 1:])]
        if inspections:
            found.append(_norm_date(*inspections[-1].groups()))
    return max(found) if found else None


def handling_result(text: str) -> str:
    parts = []
    if "责令" in text:
        parts.append("责令改正")
    if "停业" in text:
        parts.append("停业整改")
    if "没收违法所得" in text:
        parts.append("没收违法所得")
    elif "没收" in text:
        parts.append("没收涉案物品")
    total, items = fine_breakdown(text)
    if total:
        parts.append(_fine_label("罚款", total, items))
    elif "罚款" in text:
        parts.append("罚款（公告未列金额）")
    if "吊销" in text:
        parts.append("吊销许可")
    if "给予警告" in text or "警告的行政处罚" in text:
        parts.append("警告")
    if _TO_POLICE.search(text):
        parts.append("移送公安机关")
    if _POLICE_FILED.search(text):
        parts.append("公安已立案侦查")
    if not parts and _PENALIZED.search(text):
        parts.append("行政处罚（公告未列明细）")
    return "；".join(parts) or "已公开通报"


def split_regulations(lines: list[str]) -> tuple[list[str], list[str]]:
    """案件行 → (案情与处理决定, 附录的相关规定)。"""
    for i, ln in enumerate(lines):
        if _REG_HEAD.match(ln):
            return lines[:i], lines[i + 1:]
    return lines, []


def _final_at(c: str, start: int = 0) -> int | None:
    """分句里实际决定（「决定罚款」「已作出」）的位置；括号里的说明、「决定书」不算。"""
    for m in _FINAL_DECISION.finditer(c, start):
        head = c[:m.start()]
        if head.count("（") + head.count("(") > head.count("）") + head.count(")"):
            continue
        return m.start()
    return None


def _clauses(text: str) -> list[tuple[str, str]]:
    """按句号/分号拆分句，并给每个分句标类别：
    - "fact"：案情或实际决定；
    - "proposed"：拟处罚（告知阶段）——带「拟」的分句，或落在「拟作出以下行政处罚：」范围里的各项；
    - "superseded"：后来被实际决定取代的拟处罚（「原拟罚款5000元，经陈述申辩后，最终决定罚款3000元」的前半）。

    范围从引导语开始，到句号为止；跨行时，上一行以冒号、分号、逗号结尾，或下一行是「一、」「（二）」这类列表项，
    才算接着列；中途出现实际决定就结束。同一分句里先拟后决定的，在决定处拆成两段。"""
    out, scope = [], False
    for line in text.split("\n"):
        if scope and line_open is False and not _LIST_ITEM.match(line.strip()):
            scope = False
        last = ""
        for c in re.split(r"(?<=[。；;])", line):
            c = c.strip()
            if not c:
                continue
            last = c
            lead = _PROPOSAL_LEAD.search(c)
            prop = _PROPOSED.search(c)
            if lead or scope or prop:
                start = lead.end() if lead else (prop.end() if prop and not scope else 0)
                pos = _final_at(c, start)
                if pos is not None and "拟" not in c[pos:]:
                    out.append((c[:pos], "superseded"))
                    out.append((c[pos:], "fact"))
                    scope = False
                else:
                    out.append((c, "proposed"))
                    scope = scope or bool(lead)
            else:
                out.append((c, "fact"))
            if c.endswith("。"):
                scope = False
        line_open = not last or last.endswith(("：", ":", "；", ";", "，", ",", "、"))
    # 拟处罚之后又写了实际处罚决定：先前列出的拟处罚都已被取代
    for i, (c, kind) in enumerate(out):
        if kind == "fact" and _final_at(c) is not None and _PENALTY_WORD.search(c) and not _STATUTE_SENTENCE.search(c) \
                and not _CONDITIONAL.search(c):
            out[:i] = [(p, "superseded" if k == "proposed" else k) for p, k in out[:i]]
    return out



def _non_decision(c: str, kind: str) -> bool:
    if kind != "fact" or _STATUTE_SENTENCE.search(c):
        return True
    return bool(_CONDITIONAL.search(c) and _PENALTY_WORD.search(c))


def decision_text(text: str) -> str:
    """只留下叙述本案事实和实际决定的分句。去掉三类：转述法条罚则的、条件性罚则（「情节严重的，吊销……」）、
    拟处罚（告知阶段，还没决定，含「拟作出以下处罚：」后面列出的各项，以及后来被实际决定取代的原拟处罚）。"""
    return "\n".join(c for c, kind in _clauses(text) if not _non_decision(c, kind))


def proposed_result(text: str) -> str | None:
    """「拟罚款5,000元」之类：处罚告知阶段、还没有被实际决定取代的结果单独标出来，不当成已执行。"""
    kept = [c for c, kind in _clauses(text)
            if kind == "proposed" and not _STATUTE_SENTENCE.search(c) and not _CONDITIONAL.search(c)]
    if not kept:
        return None
    total, items = fine_breakdown("\n".join(kept))
    if total:
        return _fine_label("拟罚款", total, items) + "（处罚告知阶段，非最终决定）"
    return "拟作出行政处罚（处罚告知阶段，非最终决定）"


def _status_with_proposed(status: str, proposed: str | None) -> str:
    return "拟处罚（已告知）" if proposed and status in ("已通报", "责令改正", "已立案") else status


def _result_with_proposed(result: str, proposed: str | None) -> str:
    if not proposed:
        return result
    return proposed if result == "已公开通报" else f"{result}；{proposed}"


def is_catering(case_title: str, subject: str, text: str) -> bool:
    head = case_title + subject
    return any(w in head for w in _CATERING_SUBJECT) or any(w in text for w in _CATERING_BODY)


def _strip_tail(case_lines: list[str], source_name: str) -> list[str]:
    out = []
    for ln in case_lines:
        if _CASE_END.match(ln) or ln == source_name or re.fullmatch(r"\d{4}年\d{1,2}月\d{1,2}日", ln):
            break
        out.append(ln)
    return out


def parse_article(body: bytes, url: str, source: dict, listed: dict | None = None) -> dict:
    """一篇公告 → {meta..., cases:[...]}。没有案件结构时 cases 为空。"""
    lines = html_to_lines(body)
    listed = listed or {}
    title = _meta(lines, "名称") or listed.get("title") or ""
    published = (_meta(lines, "发布日期") or "").split(" ")[0] or listed.get("published_at")
    doc_no = _meta(lines, "文号") or listed.get("doc_no")
    if doc_no and doc_no.startswith(("主题词", "发布日期")):
        doc_no = None
    publisher = _meta(lines, "发布机构") or source["name"]
    body_lines = _body_lines(lines)

    heads = [(i, _CASE_HEAD.match(ln)) for i, ln in enumerate(body_lines)]
    heads = [(i, m) for i, m in heads if m]
    cases = []
    for n, (i, m) in enumerate(heads):
        end = heads[n + 1][0] if n + 1 < len(heads) else len(body_lines)
        chunk = _strip_tail(body_lines[i + 1:end], publisher)
        chunk = [_CASE_LEAD.sub("", ln, count=1) for ln in chunk]
        chunk, regs = split_regulations(chunk)
        text = "\n".join(ln for ln in chunk if ln).strip()
        if not text:
            continue
        decided = decision_text(text)
        proposed = proposed_result(text)
        case_title = m.group(3).strip()
        title_dept, _ = split_title(case_title)
        subject = subject_of(case_title, text)
        m_dept = _DEPT.search(text)
        # 办案单位：标题里写了用标题的；正文里找得到用正文的；只写「我局」的就是发布机关
        dept = title_dept or (m_dept.group(1) if m_dept else None) or ("我局" in text and publisher) or None
        total, _ = fine_breakdown(decided)
        cases.append({
            "case_no": len(cases) + 1,
            "case_title": case_title,
            "subject": subject,
            "shops": shop_names(text),
            "enforcement_dept": dept,
            "decided_at": decided_date(decided),
            "violation": text,
            "legal_basis": list(dict.fromkeys(_LAW.findall(text))),
            "regulation_text": "\n".join(ln for ln in regs if ln).strip() or None,
            "investigation_status": _status_with_proposed(investigation_status(decided), proposed),
            "handling_result": _result_with_proposed(handling_result(decided), proposed),
            "fine_amount": total,
            "is_catering": is_catering(case_title, subject, text),
        })
    return {"title": title, "url": url, "published_at": published, "doc_no": doc_no,
            "publisher": publisher, "cases": cases}


def record_key(source_id: str, url: str, case_no: int) -> str:
    """同一篇公告里的第几起案件 = 一条记录。不含当事人：解析规则升级后当事人可能变，键不能跟着变。"""
    return hashlib.sha256(f"{source_id}|{url}|{case_no}".encode("utf-8")).hexdigest()


def content_hash(case: dict) -> str:
    """案件标题 + 案情 + 附录法条。没有附录时与旧版 hash 一致，老记录不会被误判成改稿。"""
    parts = [case["case_title"], case["violation"]] + ([case["regulation_text"]] if case.get("regulation_text") else [])
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()
