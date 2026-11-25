"""来源类别与门店归属：每条内容入库时判定。

来源类别（合规口径，和「信源通道」是两个维度）：
- 官方通报  监管部门发布的通报、处罚决定；
- 媒体报道  新闻门户、媒体账号的报道；
- 品牌回应  品牌自己的官方账号发的声明；
- 顾客投诉  其余的消费者发声（评价、投诉、吐槽）。
数据里显式给了 source_category 的以数据为准。

门店归属：按门店表的名称和别名在全文里找，命中多个时取最长的那个（「人民路店」不会盖过「人民路二店」）。
"""
from ..core.config import SOURCE_CATEGORIES
from . import profile

_REGULATOR_HINTS = ("市场监督管理局", "市场监管局", "监管局", "卫生健康委", "公安局", "人民政府")


def source_category(item: dict, topic: dict | None = None) -> str:
    explicit = item.get("source_category")
    if explicit in SOURCE_CATEGORIES:
        return explicit
    author = item.get("author") or ""
    author_type = item.get("author_type") or "普通"
    if author_type in ("监管", "政府") or any(h in author for h in _REGULATOR_HINTS):
        return "官方通报"
    if author_type == "官方":
        # 「官方」账号：是品牌自己的就是品牌回应，否则按官方通报处理
        if topic is not None and profile.mentions_brand(topic, author):
            return "品牌回应"
        return "官方通报"
    if author_type == "媒体" or item.get("source_type") == "新闻门户":
        return "媒体报道"
    return "顾客投诉"


def match_store(stores: list[dict], text: str) -> dict | None:
    best, best_len = None, 0
    for s in stores:
        for alias in [s["name"], *(s.get("aliases") or [])]:
            if alias and alias in text and len(alias) > best_len:
                best, best_len = s, len(alias)
    return best
