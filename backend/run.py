"""后端启动脚本：python run.py（VS Code 按 F5 也是跑它）。"""
import uvicorn

from app.core import config

if __name__ == "__main__":
    print(f"后端接口：http://{config.HOST}:{config.PORT}{config.API_PREFIX}")
    print(f"接口文档：http://{config.HOST}:{config.PORT}/docs")
    print("页面请打开前端：http://127.0.0.1:5180")
    print("演示账号：analyst / pr / admin，密码均为 123456")
    uvicorn.run("app.main:app", host=config.HOST, port=config.PORT, reload=False,
                timeout_graceful_shutdown=2)
