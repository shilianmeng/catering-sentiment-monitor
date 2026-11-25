"""兼容根目录启动后端；前端另运行 npm run dev，或用 F5 联合启动。"""
import os
import runpy
import sys
from pathlib import Path

if __name__ == "__main__":
    backend = Path(__file__).resolve().parent / "backend"
    os.chdir(backend)
    sys.path.insert(0, str(backend))
    runpy.run_path(str(backend / "run.py"), run_name="__main__")
