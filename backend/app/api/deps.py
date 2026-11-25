"""接口层公共依赖：数据库连接、当前用户、角色校验。"""
from typing import Iterator

from fastapi import Depends, Request

from ..core.exceptions import Forbidden, Unauthorized
from ..core.security import token_store
from ..db.session import Connection, connect


def get_db() -> Iterator[Connection]:
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


def extract_token(request: Request) -> str:
    h = request.headers.get("authorization", "")
    if h.lower().startswith("bearer "):
        return h[7:].strip()
    return request.query_params.get("token") or ""


def get_current_user(request: Request) -> dict:
    user = token_store.get(extract_token(request))
    if not user:
        raise Unauthorized("未登录或登录已过期，请重新登录")
    return user


def require_role(*roles: str):
    """角色不在允许列表里返回 403。"""
    def dep(user: dict = Depends(get_current_user)) -> dict:
        if user["role"] not in roles:
            raise Forbidden("当前角色无权执行此操作")
        return user
    return dep


CurrentUser = Depends(get_current_user)
DB = Depends(get_db)
