"""登录与权限：内存 token 表 + 按角色校验的依赖。

前端把 token 放在 Authorization: Bearer 头里；SSE（EventSource 不能带头）用 ?token= 传。
服务重启 token 失效，重新登录即可。
"""
import secrets
import threading

from fastapi import Depends, HTTPException, Request

from .db import connect
from .demo import hash_password

_tokens = {}
_lock = threading.Lock()


def login(username, password):
    conn = connect()
    try:
        r = conn.execute("SELECT * FROM user WHERE username = %s", (username,)).fetchone()
    finally:
        conn.close()
    if not r or r["password_hash"] != hash_password(password or ""):
        return None
    user = {"username": r["username"], "role": r["role"], "display_name": r["display_name"]}
    token = secrets.token_urlsafe(24)
    with _lock:
        _tokens[token] = user
    return token, user


def logout(token):
    with _lock:
        _tokens.pop(token, None)


def user_for_token(token):
    with _lock:
        return _tokens.get(token)


def _extract_token(request: Request):
    h = request.headers.get("authorization", "")
    if h.lower().startswith("bearer "):
        return h[7:].strip()
    return request.query_params.get("token")


def current_user(request: Request):
    user = user_for_token(_extract_token(request) or "")
    if not user:
        raise HTTPException(401, "未登录或登录已过期，请重新登录")
    return user


def require_role(*roles):
    """接口层权限校验：角色不在允许列表里返回 403。"""
    def dep(user=Depends(current_user)):
        if user["role"] not in roles:
            raise HTTPException(403, "当前角色无权执行此操作")
        return user
    return dep
