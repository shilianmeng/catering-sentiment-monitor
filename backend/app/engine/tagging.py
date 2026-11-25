"""打标模块：情感三分类、负向细粒度情绪、敏感词命中、实体抽取。

全部是词典 + 规则，结果确定，两次运行数字一致。
词典里只放行业通用词和监管机构；品牌名、门店名这类客户独有的实体来自
topic 表（extract_entities 的 topic 参数），不写死在代码里。
"""
import re

NEG_WORDS = [
    "恶心", "脏", "想吐", "失望", "再也不", "不会再", "黑心", "无良", "太过分", "气死",
    "愤怒", "担心", "害怕", "后怕", "吓人", "不敢", "拉肚子", "腹泻", "网曝", "堪忧",
    "老鼠", "蟑螂", "变质", "过期", "退款", "赔偿", "监管", "调查", "给个说法", "交代",
    "质疑", "投诉", "维权", "起诉", "粉转黑", "寒心", "糟糕", "差劲", "停业", "慎重",
    "谁来管", "坑", "油污", "随地",
    # —— 餐饮行业扩充词（真实舆情高频，2026-11 采集验证）——
    "隐患", "责令整改", "整改", "异物", "以次充好", "虚假宣传", "冒充", "混放",
    "霉变", "脏乱差", "查封", "立案", "下架", "违规", "不合格", "残留", "虫子",
    "未公示", "速冻", "货不对板", "食物中毒", "掺假", "飞虫", "蚂蚁", "螺丝",
    "蜘蛛", "效期标签", "篡改", "隔夜", "添加剂", "毒素", "过期原料",
    "残渣", "未洗净", "水渍", "不洗手", "洗消",
]
POS_WORDS = [
    "好吃", "推荐", "满意", "喜欢", "好评", "点赞", "不错", "外酥里嫩", "支持", "认真",
    "诚意", "欢迎", "放心", "值得", "回购",
]
NEGATIONS = ("不", "没", "别")

EMOTIONS = {  # 顺序即同分时的优先级
    "愤怒": ["恶心", "黑心", "无良", "太过分", "气死", "愤怒", "退款", "赔偿", "给个说法",
             "交代", "坑", "想吐", "脏",
             "以次充好", "虚假宣传", "冒充", "货不对板", "违规", "查封", "立案",
             "掺假", "篡改", "隔夜"],
    "失望": ["失望", "再也不", "不会再", "粉转黑", "寒心", "可惜", "白瞎", "以前常去"],
    "恐慌": ["担心", "害怕", "后怕", "吓人", "不敢", "拉肚子", "腹泻", "孩子", "慎重",
             "老鼠", "蟑螂", "虫子", "异物", "霉变", "脏乱差",
             "食物中毒", "飞虫", "蚂蚁", "蜘蛛", "螺丝", "毒素"],
    "质疑": ["监管", "调查", "谁来管", "质疑", "回应", "是不是真的", "为什么", "网曝",
             "查一查", "堪忧", "真的假的", "责令整改", "隐患", "速冻", "未公示", "整改",
             "效期标签", "添加剂", "过期原料"],
}

HIGH_RISK_WORDS = ["退款", "监管", "中毒", "起诉", "维权",
                   "异物", "以次充好", "虚假宣传", "冒充",
                   "食物中毒", "掺假", "毒素"]
GENERAL_SENSITIVE_WORDS = ["卫生", "后厨", "老鼠", "蟑螂", "变质", "过期", "曝光",
                           "食品安全", "拉肚子", "停业",
                           "隐患", "责令整改", "脏乱差", "霉变", "查封", "速冻", "未公示",
                           "飞虫", "蚂蚁", "蜘蛛", "螺丝", "效期标签", "篡改", "添加剂",
                           "过期原料", "隔夜", "残渣", "未洗净", "水渍", "不洗手", "洗消"]

# 行业通用实体：监管机构、通用事件与品类。客户自己的品牌/门店不放这里。
ENTITY_DICT = {
    "市场监管局": ("机构", ["市场监管局", "市场监管部门", "市监局", "市场监管所"]),
    "消费者协会": ("机构", ["消费者协会", "消协"]),
    "后厨卫生": ("事件", ["后厨", "卫生"]),
    "食品安全": ("事件", ["食品安全"]),
    "退款诉求": ("事件", ["退款"]),
    "停业整改": ("事件", ["停业", "整改"]),
    "外卖": ("产品", ["外卖"]),
}

_CLEAN_RE = re.compile(r"[\s\W_]+", re.UNICODE)


def clean_text(text):
    """去掉空白、标点、表情等符号，只留汉字字母数字。"""
    return _CLEAN_RE.sub("", text or "")


def full_text(item):
    return " ".join(x for x in (item.get("text"), item.get("ocr_text"), item.get("asr_text")) if x)


def _count_negated(text, word):
    return sum(text.count(n + word) for n in NEGATIONS)


def sentiment_of(text):
    """返回 (情感, 正分, 负分)。否定词 + 正向词（如“不放心”）算负向。"""
    pos = neg = 0
    for w in POS_WORDS:
        total = text.count(w)
        negated = _count_negated(text, w)
        pos += total - negated
        neg += negated
    for w in NEG_WORDS:
        neg += text.count(w)
    if pos > neg:
        return "正向", pos, neg
    if neg > pos:
        return "负向", pos, neg
    return "中性", pos, neg


def emotion_of(text):
    best, best_n = None, 0
    for emo, words in EMOTIONS.items():
        n = sum(text.count(w) for w in words)
        if n > best_n:
            best, best_n = emo, n
    return best or "失望"


def sensitive_hits(text):
    return [w for w in HIGH_RISK_WORDS + GENERAL_SENSITIVE_WORDS if w in text]


def extract_entities(text, author=None, topic=None):
    """客户画像里的品牌/门店/产品（传 topic 时） + 行业通用实体。"""
    from . import profile

    found, seen = [], set()

    def add(name, etype):
        if name not in seen:
            seen.add(name)
            found.append({"name": name, "type": etype})

    if topic:
        for entity in profile.entities_of(topic):
            if any(a and a in text for a in entity["aliases"]) or (author and author == entity["name"]):
                add(entity["name"], entity["type"])
    for name, (etype, aliases) in ENTITY_DICT.items():
        if any(a in text for a in aliases) or (author and author == name):
            add(name, etype)
    return found


def tag(item, topic=None):
    """对一条内容打标，返回要写入 content 表的字段。"""
    text = full_text(item)
    senti, _, _ = sentiment_of(text)
    return {
        "sentiment": senti,
        "emotion": emotion_of(text) if senti == "负向" else None,
        "sensitive_hits": sensitive_hits(text),
        "entities": extract_entities(text, item.get("author"), topic),
    }
