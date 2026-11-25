"""通用小工具。"""
from datetime import datetime


def now_str() -> str:
    """当前真实时间，用于操作留痕（created_at 等）。"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
