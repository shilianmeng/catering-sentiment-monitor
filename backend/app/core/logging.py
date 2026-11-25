"""日志配置：控制台 + 按天滚动的文件日志（backend/logs/app.log，保留 14 天）。"""
import logging
import logging.config

from . import config


def setup_logging() -> None:
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.config.dictConfig({
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {"format": "%(asctime)s %(levelname)-5s [%(name)s] %(message)s"},
        },
        "handlers": {
            "console": {"class": "logging.StreamHandler", "formatter": "default"},
            "file": {
                "class": "logging.handlers.TimedRotatingFileHandler",
                "formatter": "default",
                "filename": str(config.LOG_DIR / "app.log"),
                "when": "midnight",
                "backupCount": 14,
                "encoding": "utf-8",
            },
        },
        "loggers": {
            "yuqing": {"handlers": ["console", "file"], "level": config.LOG_LEVEL, "propagate": False},
        },
    })


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"yuqing.{name}")
