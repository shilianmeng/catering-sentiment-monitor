"""取网页：超时 + 指数退避重试。

只重试「等一下可能就好」的错误：网络异常、超时、429、5xx。
404/403 这类重试也没用，直接抛出，交给上层记一笔跳过。
"""
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from ..core.config import COLLECT_USER_AGENT

RETRY_STATUS = {429, 500, 502, 503, 504}


class FetchError(Exception):
    def __init__(self, url: str, reason: str, status: int | None = None, attempts: int = 1):
        super().__init__(f"{url}: {reason}（尝试 {attempts} 次）")
        self.url, self.reason, self.status, self.attempts = url, reason, status, attempts


@dataclass
class Response:
    url: str
    status: int
    body: bytes
    attempts: int


def _default_open(url: str, timeout: float):
    req = urllib.request.Request(url, headers={"User-Agent": COLLECT_USER_AGENT,
                                               "Accept-Language": "zh-CN,zh;q=0.9"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read()


def fetch(url: str, *, retries: int = 3, timeout: float = 20, backoff: float = 1.0,
          opener=None, sleep=time.sleep) -> Response:
    """返回 Response；重试用尽或遇到不可重试的错误抛 FetchError。

    opener(url, timeout) -> (status, bytes)，测试里注入假的；sleep 也可注入，测试不真等。
    """
    opener = opener or _default_open
    last_reason, last_status = "", None
    for attempt in range(1, retries + 1):
        try:
            status, body = opener(url, timeout)
            if status in RETRY_STATUS:
                last_reason, last_status = f"HTTP {status}", status
            elif status >= 400:
                raise FetchError(url, f"HTTP {status}", status, attempt)
            else:
                return Response(url, status, body, attempt)
        except urllib.error.HTTPError as e:
            if e.code not in RETRY_STATUS:
                raise FetchError(url, f"HTTP {e.code}", e.code, attempt) from e
            last_reason, last_status = f"HTTP {e.code}", e.code
        except FetchError:
            raise
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            last_reason, last_status = type(e).__name__ + ": " + str(getattr(e, "reason", e)), None
        if attempt < retries:
            sleep(backoff * (2 ** (attempt - 1)))
    raise FetchError(url, last_reason or "未知错误", last_status, retries)
