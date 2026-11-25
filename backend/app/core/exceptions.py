"""业务异常与全局异常处理。

所有错误统一返回：{"code": <HTTP 状态码>, "message": <中文说明>, "detail": <同 message，兼容旧调用方>}
"""
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .logging import get_logger

log = get_logger("error")


class BizError(Exception):
    """业务异常：service 层抛出，由全局处理器转成对应 HTTP 状态码。"""
    status_code = 400

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        if status_code is not None:
            self.status_code = status_code


class BadRequest(BizError):
    status_code = 400


class Unauthorized(BizError):
    status_code = 401


class Forbidden(BizError):
    status_code = 403


class NotFound(BizError):
    status_code = 404


class Conflict(BizError):
    status_code = 409


def _body(code: int, message: str) -> dict:
    return {"code": code, "message": message, "detail": message}


_VALIDATION_MSG = {
    "missing": "缺少必填字段",
    "int_parsing": "必须是整数",
    "bool_parsing": "必须是布尔值",
    "string_type": "必须是字符串",
}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(BizError)
    async def biz_error(_: Request, exc: BizError):
        return JSONResponse(_body(exc.status_code, exc.message), status_code=exc.status_code)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException):
        msg = exc.detail if isinstance(exc.detail, str) else "请求错误"
        if exc.status_code == 404 and msg == "Not Found":
            msg = "接口不存在"
        return JSONResponse(_body(exc.status_code, msg), status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        parts = []
        for e in exc.errors():
            field = ".".join(str(x) for x in e.get("loc", []) if x not in ("body", "query", "path"))
            parts.append(f"{field or '参数'}：{_VALIDATION_MSG.get(e.get('type'), e.get('msg', '格式不正确'))}")
        return JSONResponse(_body(422, "；".join(parts) or "参数校验失败"), status_code=422)

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        log.exception("未处理异常 %s %s", request.method, request.url.path)
        return JSONResponse(_body(500, "服务器内部错误，请稍后重试"), status_code=500)
