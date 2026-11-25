"""v1 路由汇总。"""
from fastapi import APIRouter

from .endpoints import auth, contents, events, official, overview, reports, settings, stores, subjects, topics

api_router = APIRouter()
for module in (auth, overview, contents, events, reports, topics, stores, subjects, official, settings):
    api_router.include_router(module.router)
