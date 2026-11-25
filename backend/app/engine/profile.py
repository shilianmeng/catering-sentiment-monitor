"""监测对象画像：一个品牌 = 一个 topic。

代码里不再写死任何品牌、门店、产品。品牌相关的东西全部来自 topic 表：
- keywords     品牌名及别名，内容必须命中其一才归入该主题；
- brand        报告、话术里显示的品牌名（为空时取第一个关键词）；
- entities     品牌自有实体 [{name, type, aliases}]，type 取 门店/产品/人物/机构；
- event_rules  事件议题规则 [{category, title, keywords}]，title 可用 {brand} 占位；
               为空时使用下面的餐饮行业默认议题。
"""

# 餐饮行业默认议题：按命中关键词数归类，同分取靠前的
DEFAULT_EVENT_RULES = [
    {"category": "后厨卫生", "title": "{brand}·后厨卫生问题",
     "keywords": ["后厨", "卫生", "老鼠", "蟑螂", "脏", "油污", "脏乱差", "洗消", "未洗净", "不洗手"]},
    {"category": "异物", "title": "{brand}·餐品异物问题",
     "keywords": ["异物", "虫子", "飞虫", "头发", "螺丝", "蜘蛛", "蚂蚁"]},
    {"category": "食品安全", "title": "{brand}·食品安全问题",
     "keywords": ["变质", "过期", "霉变", "拉肚子", "腹泻", "食物中毒", "添加剂", "不合格", "毒素", "食品安全"]},
    {"category": "以次充好", "title": "{brand}·以次充好/虚假宣传",
     "keywords": ["以次充好", "冒充", "虚假宣传", "货不对板", "掺假", "速冻"]},
    {"category": "监管处置", "title": "{brand}·被监管部门查处",
     "keywords": ["立案", "责令整改", "处罚", "罚款", "查封", "停业", "市场监管"]},
    {"category": "服务纠纷", "title": "{brand}·服务与退款纠纷",
     "keywords": ["退款", "赔偿", "态度", "投诉", "给个说法"]},
    {"category": "口碑好评", "title": "{brand}·新品与口碑好评",
     "keywords": ["新品", "好吃", "推荐", "回购", "好评"]},
]

ENTITY_TYPES = ("门店", "产品", "人物", "机构")


def brand_of(topic: dict) -> str:
    return (topic.get("brand") or "").strip() or next(iter(topic.get("keywords") or []), "") or "品牌"


def event_rules_of(topic: dict) -> list[dict]:
    return topic.get("event_rules") or DEFAULT_EVENT_RULES


def entities_of(topic: dict) -> list[dict]:
    """品牌本身 + 品牌自有实体，统一成 {name, type, aliases}。"""
    out = [{"name": brand_of(topic), "type": "机构", "aliases": list(topic.get("keywords") or [])}]
    for e in topic.get("entities") or []:
        name = str(e.get("name") or "").strip()
        if not name:
            continue
        out.append({"name": name, "type": e.get("type") or "机构",
                    "aliases": [a for a in (e.get("aliases") or [name]) if a]})
    return out


def stores_of(topic: dict) -> list[dict]:
    return [e for e in entities_of(topic) if e["type"] == "门店"]


def mentions_brand(topic: dict, text: str) -> bool:
    return any(k and k in text for k in topic.get("keywords") or [])


def match_rule(topic: dict, text: str):
    """内容必须提到品牌，再按议题关键词命中数归类；都不命中返回 None。"""
    if not mentions_brand(topic, text):
        return None
    best, best_n = None, 0
    for rule in event_rules_of(topic):
        n = sum(1 for k in rule["keywords"] if k in text)
        if n > best_n:
            best, best_n = rule, n
    return best


def render_title(topic: dict, rule: dict) -> str:
    return rule["title"].replace("{brand}", brand_of(topic))


def store_in(topic: dict, text: str) -> str | None:
    """文本里提到的第一家门店名，没有返回 None。"""
    for s in stores_of(topic):
        if any(a in text for a in s["aliases"]):
            return s["name"]
    return None
