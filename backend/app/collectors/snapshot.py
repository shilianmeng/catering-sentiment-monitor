"""原始网页快照：按内容 SHA-256 落盘，同样的字节只存一份。

入库记录只存 hash；要核对「当时官网到底写了什么」，按 hash 找回文件即可，
官网后来改稿或下线也不影响取证。
"""
import hashlib
from datetime import datetime
from pathlib import Path

from ..core.config import BACKEND_DIR, SNAPSHOT_DIR


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def path_for(digest: str, root: Path | None = None) -> Path:
    root = Path(root or SNAPSHOT_DIR)
    return root / digest[:2] / f"{digest}.html"


def save(conn, url: str, source_id: str, body: bytes, status: int = 200, root: Path | None = None) -> str:
    """写文件 + 登记 source_snapshot；已存在则什么都不做。返回 sha256。"""
    digest = sha256(body)
    p = path_for(digest, root)
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(body)
    try:
        rel = str(p.resolve().relative_to(BACKEND_DIR))
    except ValueError:
        rel = str(p)
    conn.execute(
        "INSERT IGNORE INTO source_snapshot(sha256, url, source_id, http_status, bytes, path, fetched_at) "
        "VALUES(%s,%s,%s,%s,%s,%s,%s)",
        (digest, url, source_id, status, len(body), rel, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    return digest


def load(digest: str, root: Path | None = None) -> bytes | None:
    p = path_for(digest, root)
    if not p.exists():
        return None
    data = p.read_bytes()
    return data if sha256(data) == digest else None      # 文件被改过就不认
