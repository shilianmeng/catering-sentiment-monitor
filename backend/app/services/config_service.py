"""监测配置：预警阈值、等级分数线、通知渠道。"""
from ..core.exceptions import BadRequest
from ..db.session import get_config, set_config, write_lock
from ..engine import agent, demo

CONFIG_KEYS = (
    "surge_threshold", "surge_min_count", "level_s", "level_a", "level_b",
    "silence_minutes", "kol_alert_weight", "notify_site", "notify_email", "notify_sms",
)


def get(conn) -> dict:
    cfg = get_config(conn)
    return {k: cfg[k] for k in CONFIG_KEYS} | {"llm_model": cfg["llm_model"],
                                              "llm_available": agent.llm_available()}


def update(conn, changes: dict) -> dict:
    changes = {k: v for k, v in changes.items() if k in CONFIG_KEYS and v is not None}
    new = {**get_config(conn), **changes}
    if not new["level_s"] > new["level_a"] > new["level_b"]:
        raise BadRequest("等级分数线必须满足 S > A > B")
    with write_lock:
        for k, v in changes.items():
            set_config(conn, k, v)
        conn.commit()
    if any(k.startswith("level_") for k in changes):
        demo.recompute_all_levels()       # 分数线变了，立即按新阈值重算所有事件等级
    return get(conn)
