"""登录 / 登出 / 当前用户。"""
from fastapi import APIRouter, Request

from ....engine import agent
from ....schemas import LoginIn
from ....services import auth_service
from ...deps import DB, CurrentUser, extract_token

router = APIRouter(tags=["认证"])


@router.post("/login", summary="登录")
def login(body: LoginIn, conn=DB):
    return auth_service.login(conn, body.username, body.password)


@router.post("/logout", summary="登出")
def logout(request: Request, user=CurrentUser):
    auth_service.logout(extract_token(request))
    return {"ok": True}


@router.get("/me", summary="当前用户")
def me(user=CurrentUser):
    return {**user, "llm_available": agent.llm_available()}
