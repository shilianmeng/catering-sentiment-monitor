"""应用配置：集中管理连接参数、端口、业务常量。

约定：
- 凭据只从环境变量或 backend/.env 读取，代码里不保存任何 key、密码；
  .env 不进版本库（.gitignore 已排除），仓库里只有 .env.example。
- 本地开发开箱即用：不配 .env 时用本机默认值（MySQL root/root、无大模型 key），
  没有大模型 key 时研判文字自动降级为模板生成，功能不受影响。
- 部署到其他环境时，用同名环境变量覆盖即可（12-Factor 风格），代码不用改。
- 所有路径都相对 backend 目录计算，整个项目文件夹搬走也能跑。
"""
import os
from pathlib import Path


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _env_list(name: str, default: str) -> list[str]:
    return [x.strip() for x in _env(name, default).split(",") if x.strip()]


BACKEND_DIR = Path(__file__).resolve().parents[2]


def _load_dotenv(path: Path) -> None:
    """读取 backend/.env（一行一条 KEY=VALUE）；已存在的环境变量优先，不覆盖。"""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(BACKEND_DIR / ".env")


def _load_secrets(path: Path) -> None:
    """读取 backend/secrets.local.json（不进版本库）；已存在的环境变量优先。"""
    import json

    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return
    mapping = {
        "openai_api_key": "OPENAI_API_KEY",
        "mysql_password": "YUQING_MYSQL_PASSWORD",
        "mysql_user": "YUQING_MYSQL_USER",
        "mysql_host": "YUQING_MYSQL_HOST",
        "mysql_database": "YUQING_MYSQL_DATABASE",
    }
    for key, env_name in mapping.items():
        value = data.get(key)
        if value not in (None, ""):
            os.environ.setdefault(env_name, str(value))


_load_secrets(BACKEND_DIR / "secrets.local.json")

SEED_FILE = BACKEND_DIR / "app" / "engine" / "seed_data.json"
LOG_DIR = BACKEND_DIR / "logs"

# 平台名与品牌无关：品牌写在「监测主题」里，一个客户总部一个主题。
APP_NAME = _env("YUQING_APP_NAME", "餐饮舆情监测与研判平台")
APP_VERSION = "2.2.0"
API_PREFIX = "/api/v1"
ENV = _env("YUQING_ENV", "dev")                 # dev / test / prod
LOG_LEVEL = _env("YUQING_LOG_LEVEL", "INFO")

HOST = _env("YUQING_HOST", "127.0.0.1")
PORT = int(_env("YUQING_PORT", "8091"))         # 本机 8000 被其他项目占用，不要改成 8000

# 允许跨域访问的前端地址（开发时前端走 Vite 代理，一般用不到；前端单独部署时用）
CORS_ORIGINS = _env_list("YUQING_CORS_ORIGINS", "http://127.0.0.1:5180,http://localhost:5180")

# 登录 token 有效期（小时）
TOKEN_TTL_HOURS = int(_env("YUQING_TOKEN_TTL_HOURS", "12"))

# MySQL 连接参数：本机默认 root/root，可用 backend/.env 覆盖。
MYSQL = {
    "host": _env("YUQING_MYSQL_HOST", "127.0.0.1"),
    "port": int(_env("YUQING_MYSQL_PORT", "3306")),
    "user": _env("YUQING_MYSQL_USER", "root"),
    "password": _env("YUQING_MYSQL_PASSWORD", "root"),
    "database": _env("YUQING_MYSQL_DATABASE", "YuQing"),
}

OPENAI_MODEL = _env("OPENAI_MODEL", "gpt-4o-mini")
# 大模型 key 只从环境变量或 backend/.env 读取；为空时全部走模板生成（报告会标注「模板生成」）。
OPENAI_API_KEY = _env("OPENAI_API_KEY", "").strip()

# 虚拟时钟：批次按 0–7 连续编号，页面显示 T0…T6 和 T2.5
BATCHES = [
    {"no": 0, "label": "T0", "time": "2026-11-18 12:00"},
    {"no": 1, "label": "T1", "time": "2026-11-18 13:00"},
    {"no": 2, "label": "T2", "time": "2026-11-18 14:00"},
    {"no": 3, "label": "T2.5", "time": "2026-11-18 14:30"},
    {"no": 4, "label": "T3", "time": "2026-11-18 15:00"},
    {"no": 5, "label": "T4", "time": "2026-11-18 16:00"},
    {"no": 6, "label": "T5", "time": "2026-11-18 17:00"},
    {"no": 7, "label": "T6", "time": "2026-11-18 18:00"},
]
LAST_BATCH = BATCHES[-1]["no"]

# 信源通道（采集渠道），与「来源类别」是两个维度：前者是技术通道，后者是合规口径。
SOURCE_TYPES = ["社交媒体", "新闻门户", "短视频平台", "行业论坛"]

# 来源类别：官方通报 / 媒体报道 / 顾客投诉 / 品牌回应。几类的研判规则完全不同，必须分开。
# 「品牌回应」是品牌自己的声明：既不是监管结论，也不是第三方报道，单列出来不混算。
SOURCE_CATEGORIES = ["官方通报", "媒体报道", "顾客投诉", "品牌回应"]
# 每条内容必须具备的证据字段（缺失时报告不出结论，只标注「待补」）。
EVIDENCE_FIELDS = ["official_url", "store_subject", "investigation_status", "handling_result"]

# 门店经营方式
STORE_OWNERSHIP = ["直营", "加盟"]

# 官方处罚公示源：真实采集。两家都是广东「政府信息公开目录平台」（gkmlpt），
# 列表走 JSON 接口，正文是静态页；典型案例公告一篇里有多起案件，逐案拆成记录。
OFFICIAL_SOURCES = [
    {"id": "gz_amr", "name": "广州市市场监督管理局", "region": "广东省广州市",
     "base_url": "http://scjgj.gz.gov.cn", "sid": "200039"},
    {"id": "sz_amr", "name": "深圳市市场监督管理局", "region": "广东省深圳市",
     "base_url": "https://amr.sz.gov.cn", "sid": None},
]
# 原始网页快照目录（不进版本库；入库记录里存 sha256，可按 hash 找回原文）
SNAPSHOT_DIR = Path(_env("YUQING_SNAPSHOT_DIR", str(BACKEND_DIR / "data" / "snapshots")))
# 随仓库提交的真实官方处罚记录（由采集器真实抓取生成，离线演示时直接灌库）
OFFICIAL_SEED_FILE = BACKEND_DIR / "app" / "engine" / "official_seed.json"
COLLECT_USER_AGENT = _env("YUQING_COLLECT_UA", "Mozilla/5.0 (compatible; yuqing-collector/2.2)")

STATUSES = ["待处理", "跟踪中", "已核实", "已处理", "辟谣处理", "忽略"]
TERMINAL_STATUSES = {"已处理", "辟谣处理", "忽略"}
# 处置状态机：只允许相邻流转；「忽略」可从任何未结束状态进入
NEXT_STATUS = {
    "待处理": ["跟踪中", "忽略"],
    "跟踪中": ["已核实", "忽略"],
    "已核实": ["已处理", "辟谣处理", "忽略"],
}

ROLES = {"analyst": "分析师", "pr": "公关", "admin": "管理员"}

DEFAULT_CONFIG = {
    "surge_threshold": 150,      # 单小时负向声量环比增幅阈值（%）
    "surge_min_count": 10,       # 本小时负向条数至少这么多才算激增，避免基数太小误报
    "level_s": 85,
    "level_a": 70,
    "level_b": 50,
    "silence_minutes": 60,       # 同事件静默期（虚拟分钟）
    "kol_alert_weight": 9,       # 账号权重 ≥ 此值发声才触发 KOL 预警
    "notify_site": True,         # 站内通知
    "notify_email": False,       # 邮件（模拟）
    "notify_sms": False,         # 短信（模拟）
    "llm_model": OPENAI_MODEL,
}


def batch_label(no):
    for b in BATCHES:
        if b["no"] == no:
            return b["label"]
    return "-"


def batch_time(no):
    for b in BATCHES:
        if b["no"] == no:
            return b["time"]
    return None
