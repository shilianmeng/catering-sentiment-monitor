"""应用入口：create_app() 组装中间件、异常处理、路由。

前后端分离：本服务只提供 /api/v1 下的 JSON 接口和 SSE 推送；页面由 frontend（Vue 3）提供。
接口文档：http://127.0.0.1:8091/docs
"""
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from .api.v1.router import api_router
from .core import config
from .core.exceptions import register_exception_handlers
from .core.logging import get_logger, setup_logging
from .engine import demo

log = get_logger("app")


@asynccontextmanager
async def lifespan(_: FastAPI):
    demo.ensure_db()          # 首次启动没有表就自动建表并灌入演示数据
    log.info("%s v%s 已启动，数据库 %s", config.APP_NAME, config.APP_VERSION, config.MYSQL["database"])
    yield
    log.info("服务已停止")


def create_app() -> FastAPI:
    setup_logging()
    app = FastAPI(title=config.APP_NAME, version=config.APP_VERSION, lifespan=lifespan,
                  docs_url="/docs", redoc_url=None, openapi_url="/openapi.json")

    app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"], expose_headers=["Content-Disposition"])

    @app.middleware("http")
    async def access_log(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        if request.url.path.startswith(config.API_PREFIX) and not request.url.path.endswith("/stream"):
            log.info("%s %s -> %s (%.0fms)", request.method, request.url.path, response.status_code,
                     (time.perf_counter() - start) * 1000)
        return response

    register_exception_handlers(app)
    app.include_router(api_router, prefix=config.API_PREFIX)

    @app.get("/health", tags=["运维"], summary="健康检查")
    def health():
        return {"status": "ok", "name": config.APP_NAME, "version": config.APP_VERSION}

    return app


app = create_app()
