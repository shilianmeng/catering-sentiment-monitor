"""认证与鉴权：密码哈希、token 签发/校验、按角色授权。

- 密码用 PBKDF2-HMAC-SHA256 + 随机盐；早期无盐 SHA-256 的历史记录仍能登录，
  登录成功后由调用方按 needs_rehash 平滑升级。
- 会话落库：auth_session 表只存 token 的 SHA-256（库被读走也拿不到可用的 token），
  服务重启不丢登录；进程内保留一层缓存，正常请求不查库。
- 前端在 Authorization: Bearer <token> 头里携带；SSE（EventSource 不能带头）用 ?token= 传。
"""
import hashlib
import hmac
import secrets
import threading
import time
from dataclasses import dataclass

from . import config

PBKDF2_ITERATIONS = 240_000
_HASH_PREFIX = "pbkdf2_sha256"


def hash_password(pw: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", (pw or "").encode("utf-8"), salt.encode("utf-8"),
                                 PBKDF2_ITERATIONS)
    return f"{_HASH_PREFIX}${PBKDF2_ITERATIONS}${salt}${digest.hex()}"


def _legacy_hash(pw: str) -> str:
    return hashlib.sha256((pw or "").encode("utf-8")).hexdigest()


def verify_password(pw: str, password_hash: str) -> bool:
    if not password_hash:
        return False
    if password_hash.startswith(_HASH_PREFIX + "$"):
        try:
            _, iterations, salt, digest = password_hash.split("$", 3)
            calc = hashlib.pbkdf2_hmac("sha256", (pw or "").encode("utf-8"),
                                       salt.encode("utf-8"), int(iterations))
        except (ValueError, TypeError):
            return False
        return hmac.compare_digest(calc.hex(), digest)
    return hmac.compare_digest(_legacy_hash(pw), password_hash)


def needs_rehash(password_hash: str) -> bool:
    """老格式（无盐 SHA-256）返回 True，登录成功后应重算一遍存回去。"""
    return not (password_hash or "").startswith(_HASH_PREFIX + "$")


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass
class _Cached:
    user: dict
    expires_at: float


class TokenStore:
    """token → 用户。写入 auth_session 表，读时先看内存缓存，缓存没有才查库。"""

    def __init__(self, ttl_seconds: int):
        self._ttl = ttl_seconds
        self._cache: dict[str, _Cached] = {}
        self._lock = threading.Lock()

    def issue(self, user: dict) -> str:
        token = secrets.token_urlsafe(24)
        expires_at = time.time() + self._ttl
        with self._lock:
            self._cache[token] = _Cached(dict(user), expires_at)
        self._persist(token, user, expires_at)
        return token

    def get(self, token: str) -> dict | None:
        if not token:
            return None
        now = time.time()
        with self._lock:
            hit = self._cache.get(token)
            if hit and hit.expires_at > now:
                return hit.user
            self._cache.pop(token, None)
        row = self._load(token)
        if not row:
            return None
        expires_at = float(row["expires_at"])
        if expires_at <= now:
            self.revoke(token)
            return None
        user = {"username": row["username"], "role": row["role"], "display_name": row["display_name"]}
        with self._lock:
            self._cache[token] = _Cached(user, expires_at)
        return user

    def revoke(self, token: str) -> None:
        with self._lock:
            self._cache.pop(token, None)
        try:
            from ..db.session import connect
            conn = connect()
            try:
                conn.execute("DELETE FROM auth_session WHERE token_hash = %s", (_token_hash(token),))
                conn.commit()
            finally:
                conn.close()
        except Exception:  # noqa: BLE001 —— 库不可用时至少把本地缓存清掉
            pass

    def _persist(self, token: str, user: dict, expires_at: float) -> None:
        try:
            from ..db.session import connect
            conn = connect()
            try:
                conn.execute("DELETE FROM auth_session WHERE expires_at < %s", (time.time(),))
                conn.execute(
                    "INSERT INTO auth_session(token_hash, username, role, display_name, expires_at, created_at) "
                    "VALUES(%s,%s,%s,%s,%s,%s)",
                    (_token_hash(token), user.get("username"), user.get("role"),
                     user.get("display_name"), expires_at,
                     time.strftime("%Y-%m-%d %H:%M:%S")),
                )
                conn.commit()
            finally:
                conn.close()
        except Exception:  # noqa: BLE001 —— 落库失败不阻断登录，退化为进程内会话
            pass

    def _load(self, token: str):
        try:
            from ..db.session import connect
            conn = connect()
            try:
                return conn.execute(
                    "SELECT username, role, display_name, expires_at FROM auth_session WHERE token_hash = %s",
                    (_token_hash(token),)).fetchone()
            finally:
                conn.close()
        except Exception:  # noqa: BLE001 —— 表还没建或库不可用
            return None


token_store = TokenStore(config.TOKEN_TTL_HOURS * 3600)
