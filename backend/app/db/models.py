"""MySQL 8.0 / InnoDB 建表语句。内容表与事件表分开；处置和人工改级各有一张留痕表。

品牌不写进代码：一个客户总部 = 一条 topic，品牌名、别名、事件议题规则、门店清单
都存在 topic 表里（brand / entities / event_rules），换客户只改数据。
"""
DDL = """
CREATE TABLE IF NOT EXISTS user (
    id INTEGER PRIMARY KEY AUTO_INCREMENT,
    username VARCHAR(191) UNIQUE NOT NULL,
    password_hash LONGTEXT NOT NULL,
    role LONGTEXT NOT NULL,
    display_name LONGTEXT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS auth_session (
    token_hash VARCHAR(64) PRIMARY KEY,   -- 只存 token 的 SHA-256，库被读走也拿不到可用 token
    username VARCHAR(191) NOT NULL,
    role LONGTEXT NOT NULL,
    display_name LONGTEXT,
    expires_at DOUBLE NOT NULL,           -- Unix 时间戳（秒）
    created_at LONGTEXT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS topic (
    id INTEGER PRIMARY KEY AUTO_INCREMENT,
    name LONGTEXT NOT NULL,
    keywords LONGTEXT NOT NULL,          -- JSON 数组：品牌名与别名，内容命中其一才归入该主题
    channels LONGTEXT NOT NULL,          -- JSON 对象：四类信源通道开关
    brand LONGTEXT,                      -- 报告与话术里显示的品牌名
    entities LONGTEXT,                   -- JSON：[{name,type,aliases}]，type 取 门店/产品/人物/机构
    event_rules LONGTEXT,                -- JSON：[{category,title,keywords}]，为空时走行业默认议题
    created_by LONGTEXT,
    enabled INTEGER NOT NULL DEFAULT 1
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS config (
    `key` VARCHAR(191) PRIMARY KEY,
    value LONGTEXT NOT NULL              -- JSON
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS event (
    id VARCHAR(191) PRIMARY KEY,
    topic_id INTEGER,
    category LONGTEXT,
    title LONGTEXT NOT NULL,
    keywords LONGTEXT,                   -- JSON 数组
    level VARCHAR(32) NOT NULL DEFAULT 'C',
    intensity_score INTEGER NOT NULL DEFAULT 0,
    score_speed INTEGER DEFAULT 0,
    score_interaction INTEGER DEFAULT 0,
    score_kol INTEGER DEFAULT 0,
    score_sensitive INTEGER DEFAULT 0,
    score_basis LONGTEXT,                -- JSON：四项分的计算依据
    auto_level VARCHAR(32) DEFAULT 'C',
    auto_score INTEGER DEFAULT 0,
    manual_override INTEGER NOT NULL DEFAULT 0,
    manual_level LONGTEXT,
    manual_reason LONGTEXT,
    manual_by LONGTEXT,
    manual_at LONGTEXT,
    first_content_id LONGTEXT,
    status VARCHAR(32) NOT NULL DEFAULT '待处理',
    peak_volume INTEGER DEFAULT 0,
    created_at LONGTEXT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS content (
    id VARCHAR(191) PRIMARY KEY,
    event_id VARCHAR(191),
    topic_id INTEGER,
    source_type LONGTEXT NOT NULL,
    platform LONGTEXT,
    author LONGTEXT,
    author_type LONGTEXT,
    kol_weight INTEGER DEFAULT 0,
    published_at LONGTEXT NOT NULL,
    text LONGTEXT NOT NULL,
    media_type VARCHAR(32) NOT NULL DEFAULT 'text',
    ocr_text LONGTEXT,
    asr_text LONGTEXT,
    parent_id LONGTEXT,
    reposts INTEGER DEFAULT 0,
    comments INTEGER DEFAULT 0,
    likes INTEGER DEFAULT 0,
    simhash LONGTEXT,
    sentiment LONGTEXT,
    emotion LONGTEXT,
    sensitive_hits LONGTEXT,             -- JSON 数组
    entities LONGTEXT,                   -- JSON 数组 [{name,type}]
    batch_no INTEGER,
    dup_count INTEGER NOT NULL DEFAULT 0,
    dup_of LONGTEXT,                     -- 水军近似帖：并入的首发 content id
    source_category VARCHAR(32),         -- 官方通报 / 媒体报道 / 顾客投诉 / 品牌回应
    store_id INTEGER,                    -- 落到哪家门店（store.id），认不出为空
    store_subject LONGTEXT,              -- 门店主体名称（原文里的叫法）
    official_url LONGTEXT,               -- 官方原文链接（官方通报必填）
    investigation_status LONGTEXT,       -- 调查状态：已立案 / 已处罚 / 移送公安 …
    handling_result LONGTEXT,            -- 处理结果：罚款金额、责令改正 …
    official_record_id INTEGER,          -- 对应的 official_record.id
    INDEX idx_content_event (event_id),
    INDEX idx_content_batch (batch_no)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS alert (
    id INTEGER PRIMARY KEY AUTO_INCREMENT,
    event_id VARCHAR(191),
    alert_type LONGTEXT NOT NULL,        -- 激增 / 敏感词 / KOL发声 / 升级
    rule_desc LONGTEXT,
    level VARCHAR(32),
    summary LONGTEXT,
    triggered_at LONGTEXT,
    batch_no INTEGER,
    silence_until LONGTEXT,
    suppressed INTEGER NOT NULL DEFAULT 0,   -- 1 = 静默期内已抑制，只留记录不通知
    notified LONGTEXT,                   -- JSON：已推送的渠道
    is_read INTEGER NOT NULL DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS disposal_action (
    id INTEGER PRIMARY KEY AUTO_INCREMENT,
    event_id VARCHAR(191) NOT NULL,
    from_status LONGTEXT,
    to_status LONGTEXT NOT NULL,
    operator LONGTEXT NOT NULL,
    role LONGTEXT NOT NULL,
    note LONGTEXT,
    created_at LONGTEXT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS level_adjustment (
    id INTEGER PRIMARY KEY AUTO_INCREMENT,
    event_id VARCHAR(191) NOT NULL,
    auto_level VARCHAR(32),
    auto_score INTEGER,
    new_level LONGTEXT NOT NULL,
    reason LONGTEXT,
    operator LONGTEXT NOT NULL,
    created_at LONGTEXT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS opinion_cluster (
    id INTEGER PRIMARY KEY AUTO_INCREMENT,
    event_id VARCHAR(191) NOT NULL,
    summary LONGTEXT NOT NULL,
    sentiment LONGTEXT,
    emotion LONGTEXT,
    representative_content_ids LONGTEXT, -- JSON 数组
    count INTEGER NOT NULL DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS response_draft (
    id INTEGER PRIMARY KEY AUTO_INCREMENT,
    event_id VARCHAR(191) NOT NULL,
    content LONGTEXT NOT NULL,
    gen_mode LONGTEXT NOT NULL,
    model_name LONGTEXT,
    created_by LONGTEXT,
    created_at LONGTEXT NOT NULL,
    adopted INTEGER NOT NULL DEFAULT 0,
    adopted_by LONGTEXT,
    adopted_at LONGTEXT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS report (
    id INTEGER PRIMARY KEY AUTO_INCREMENT,
    event_id VARCHAR(191) NOT NULL,
    title LONGTEXT NOT NULL,
    sections LONGTEXT NOT NULL,          -- JSON：五节 [{title, body}]
    disposal_log LONGTEXT,               -- JSON
    gen_mode LONGTEXT NOT NULL,
    model_name LONGTEXT,
    created_by LONGTEXT,
    created_at LONGTEXT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS store (
    id INTEGER PRIMARY KEY AUTO_INCREMENT,
    topic_id INTEGER NOT NULL,           -- 属于哪个品牌（topic）
    name VARCHAR(191) NOT NULL,          -- 门店全称，如「品牌·某某路店」
    aliases LONGTEXT,                    -- JSON 数组：文本里的其他叫法
    ownership VARCHAR(16) NOT NULL DEFAULT '直营',   -- 直营 / 加盟
    province LONGTEXT,
    city LONGTEXT,
    district LONGTEXT,
    address LONGTEXT,
    license_subject LONGTEXT,            -- 营业执照上的经营主体（加盟店往往是另一家公司）
    status VARCHAR(16) NOT NULL DEFAULT '营业',      -- 营业 / 停业整改 / 已关店
    UNIQUE KEY uk_store_topic_name (topic_id, name),
    INDEX idx_store_topic (topic_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS source_snapshot (
    sha256 CHAR(64) PRIMARY KEY,         -- 原始网页字节的 SHA-256；同一内容只存一份
    url LONGTEXT NOT NULL,
    source_id VARCHAR(32) NOT NULL,
    http_status INTEGER,
    bytes INTEGER NOT NULL,
    path LONGTEXT,                       -- 本地快照文件（相对 backend 目录）
    fetched_at LONGTEXT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS official_record (
    id INTEGER PRIMARY KEY AUTO_INCREMENT,
    record_key CHAR(64) NOT NULL,        -- 去重键：sha256(来源 + 原文链接 + 案件序号 + 当事人)
    content_hash CHAR(64) NOT NULL,      -- 案件正文的 hash；同一键正文变了说明官方改过稿
    source_id VARCHAR(32) NOT NULL,
    source_name LONGTEXT NOT NULL,       -- 发布机关
    source_category VARCHAR(32) NOT NULL DEFAULT '官方通报',
    official_url LONGTEXT NOT NULL,      -- 官方原文链接
    article_title LONGTEXT,              -- 公告标题
    doc_no LONGTEXT,                     -- 文号
    case_no INTEGER NOT NULL,            -- 公告里的第几起案件
    case_title LONGTEXT NOT NULL,
    subject LONGTEXT,                    -- 当事人 / 门店主体
    enforcement_dept LONGTEXT,           -- 办案单位（区局）
    region LONGTEXT,
    published_at VARCHAR(32),            -- 公告发布日期
    decided_at VARCHAR(32),              -- 案件里能找到的最近处理日期
    violation LONGTEXT,                  -- 案情原文
    legal_basis LONGTEXT,                -- JSON 数组：引用的法条
    regulation_text LONGTEXT,            -- 公告附的「相关规定」法条原文：只是可能的罚则，不是本案决定
    investigation_status VARCHAR(32),    -- 已处罚 / 移送公安 / 公安已立案 / 责令改正
    handling_result LONGTEXT,            -- 处理结果摘要
    fine_amount DOUBLE,                  -- 罚款金额（元），没有为空
    is_catering INTEGER NOT NULL DEFAULT 0,  -- 是否餐饮服务主体
    topic_id INTEGER,                    -- 认出属于哪个品牌时回填
    store_id INTEGER,
    snapshot_sha256 CHAR(64),            -- 对应 source_snapshot
    fetched_at LONGTEXT,
    revision INTEGER NOT NULL DEFAULT 1, -- 官方改稿次数 + 1
    parser_version INTEGER NOT NULL DEFAULT 0, -- 解析规则版本；同一快照只允许更新版本的解析覆盖
    UNIQUE KEY uk_official_key (record_key),
    INDEX idx_official_topic (topic_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
"""

TABLES = [
    "user", "auth_session", "topic", "config", "event", "content", "alert",
    "disposal_action", "level_adjustment", "opinion_cluster", "response_draft", "report",
    "store", "source_snapshot", "official_record",
]

# 「重置演示」只重建业务表；登录会话保留，重置一下不该把所有人都踢下线。
# 官方快照和官方处罚记录是真实抓下来的证据，重置演示也不该丢（重置后重新关联品牌/门店）。
KEEP_ON_RESET = {"auth_session", "source_snapshot", "official_record"}

# 老库升级：CREATE TABLE IF NOT EXISTS 不会给已存在的表加字段，这里声明缺哪列补哪列。
COLUMN_MIGRATIONS = {
    "topic": [
        ("brand", "LONGTEXT"),
        ("entities", "LONGTEXT"),
        ("event_rules", "LONGTEXT"),
    ],
    # 早先手工建过一版 store（只有 type/region），这里补齐新字段；ownership 由 demo.backfill_store_fields 从 type 回填
    "store": [
        ("aliases", "LONGTEXT"),
        ("ownership", "VARCHAR(16) NOT NULL DEFAULT '直营'"),
        ("province", "LONGTEXT"),
        ("city", "LONGTEXT"),
        ("district", "LONGTEXT"),
        ("license_subject", "LONGTEXT"),
    ],
    "content": [
        ("source_category", "VARCHAR(32)"),
        ("store_id", "INTEGER"),
        ("store_subject", "LONGTEXT"),
        ("official_url", "LONGTEXT"),
        ("investigation_status", "LONGTEXT"),
        ("handling_result", "LONGTEXT"),
        ("official_record_id", "INTEGER"),
    ],
    "official_record": [
        ("regulation_text", "LONGTEXT"),
        ("parser_version", "INTEGER NOT NULL DEFAULT 0"),
    ],
}
