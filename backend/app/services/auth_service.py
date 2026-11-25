"""登录、登出。"""
from ..core.exceptions import Unauthorized
from ..core.security import hash_password, needs_rehash, token_store, verify_password
from ..repositories import user_repo


def login(conn, username: str, password: str) -> dict:
    r = user_repo.get_user(conn, username.strip())
    if not r or not verify_password(password, r["password_hash"]):
        raise Unauthorized("用户名或密码错误")
    if needs_rehash(r["password_hash"]):
        # 老库里的无盐 SHA-256 哈希，趁这次登录密码还在手上，平滑升级为 PBKDF2
        conn.execute("UPDATE user SET password_hash = %s WHERE username = %s",
                     (hash_password(password), r["username"]))
        conn.commit()
    user = {"username": r["username"], "role": r["role"], "display_name": r["display_name"]}
    return {"token": token_store.issue(user), **user}


def logout(token: str) -> None:
    token_store.revoke(token)
