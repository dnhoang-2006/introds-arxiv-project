"""
http_utils.py — Lớp HTTP "lịch sự" dùng chung cho mọi request tới arXiv.

Đảm bảo 3 ràng buộc cứng:
  1. Chờ >= 3 giây giữa 2 request liên tiếp   -> RateLimiter
  2. Chỉ 1 connection tại một thời điểm         -> khóa quanh cả request + pool 1 connection
  3. User-Agent mô tả rõ danh tính               -> config.USER_AGENT

Thêm: retry exponential backoff (có jitter) cho 429 / 5xx / lỗi mạng,
tôn trọng header Retry-After nếu server gửi.

Thread-safe: tuần 2 có nhiều luồng gọi vào thì khóa vẫn ép đúng 1 connection.
"""

from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass

import requests
from requests.adapters import HTTPAdapter

import config

HTTP_OK = 200
RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
MIN_DELAY = 3.0  # arXiv: "wait at least 3 seconds between successive calls"
FORBIDDEN_HOSTS = ("://arxiv.org", "://www.arxiv.org")
CHUNK_SIZE = 1 << 16  # 64 KiB


class TransferIncomplete(requests.RequestException):
    """Server ngắt kết nối trước khi gửi đủ Content-Length."""


@dataclass(frozen=True)
class FetchResult:
    """Kết quả cuối cùng của một lần GET, sau khi đã retry xong."""

    url: str
    status: int | None  # HTTP status cuối cùng; None nếu không nhận được phản hồi
    content: bytes  # body; b"" khi lỗi
    seconds: float  # từ lúc gửi request đầu tiên đến khi xong, gồm cả chờ retry,
    # KHÔNG gồm thời gian chờ pacing trước request đầu tiên
    attempts: int
    error_type: str = ""  # rỗng khi thành công; vd "timeout", "http_404", "incomplete_read"

    @property
    def ok(self) -> bool:
        return self.status == HTTP_OK and not self.error_type


class RateLimiter:
    """Giữ khoảng cách tối thiểu giữa 2 lần bắt đầu request."""

    def __init__(self, min_interval: float) -> None:
        self.min_interval = min_interval
        self._last = float("-inf")

    def wait(self) -> None:
        remaining = self.min_interval - (time.monotonic() - self._last)
        if remaining > 0:
            time.sleep(remaining)
        self._last = time.monotonic()


class PoliteSession:
    """requests.Session bọc pacing, giới hạn 1 connection và retry.

    Ví dụ:
        with PoliteSession() as http:
            res = http.get("https://export.arxiv.org/src/2310.12345v1")
    """

    def __init__(
        self,
        delay: float = config.REQUEST_DELAY,
        timeout: float = config.HTTP_TIMEOUT,
        max_retries: int = config.MAX_RETRIES,
        backoff_base: float = 5.0,
        backoff_max: float = 120.0,
    ) -> None:
        if delay < MIN_DELAY:
            raise ValueError(f"arXiv yêu cầu delay >= {MIN_DELAY} giây — không được giảm.")
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.backoff_max = backoff_max
        self._limiter = RateLimiter(delay)
        self._lock = threading.Lock()

        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": config.USER_AGENT,
                # File /src/ vốn đã là gzip -> không cho server nén thêm lúc truyền.
                "Accept-Encoding": "identity",
            }
        )
        adapter = HTTPAdapter(pool_connections=1, pool_maxsize=1, pool_block=True, max_retries=0)
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)

    # ------------------------------------------------------------------
    def _backoff(self, attempt: int, retry_after: str | None = None) -> float:
        if retry_after and retry_after.isdigit():
            return min(float(retry_after), self.backoff_max)
        delay = min(self.backoff_base * 2 ** (attempt - 1), self.backoff_max)
        return delay * random.uniform(0.8, 1.2)

    def _request_once(self, url: str) -> tuple[int, bytes, str | None]:
        """Gửi 1 request. Trả (status, body, retry_after). Ném lỗi mạng nếu có."""
        with self._session.get(url, timeout=self.timeout, stream=True) as resp:
            if resp.status_code != HTTP_OK:
                return resp.status_code, b"", resp.headers.get("Retry-After")
            body = b"".join(resp.iter_content(chunk_size=CHUNK_SIZE))
            expected = resp.headers.get("Content-Length", "")
            if expected.isdigit() and len(body) < int(expected):
                raise TransferIncomplete(f"nhận {len(body)}/{expected} bytes")
            return HTTP_OK, body, None

    def get(self, url: str) -> FetchResult:
        if any(host in url for host in FORBIDDEN_HOSTS):
            raise ValueError(f"Cấm gọi domain chính arxiv.org: {url}")

        status: int | None = None
        error = "other"
        started: float | None = None
        attempt = 0

        with self._lock:
            for attempt in range(1, self.max_retries + 2):  # 1 lần đầu + max_retries
                self._limiter.wait()
                started = started or time.perf_counter()
                retry_after = None
                try:
                    status, body, retry_after = self._request_once(url)
                    if status == HTTP_OK:
                        return FetchResult(
                            url, HTTP_OK, body, time.perf_counter() - started, attempt
                        )
                    error = f"http_{status}"
                    if status not in RETRY_STATUS:
                        break  # 403/404...: thử lại vô ích
                except requests.Timeout:
                    status, error = None, "timeout"
                except (
                    requests.exceptions.ChunkedEncodingError,
                    requests.exceptions.ContentDecodingError,
                    TransferIncomplete,
                ):
                    status, error = None, "incomplete_read"
                except requests.ConnectionError:
                    status, error = None, "connection_error"
                except requests.RequestException as exc:
                    status, error = None, type(exc).__name__

                if attempt <= self.max_retries:
                    time.sleep(self._backoff(attempt, retry_after))

        elapsed = time.perf_counter() - started if started else 0.0
        return FetchResult(url, status, b"", elapsed, attempt, error_type=error)

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> PoliteSession:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()