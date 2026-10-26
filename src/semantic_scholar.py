"""Gọi Semantic Scholar tuần tự, có pacing, timeout và retry hữu hạn."""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable
from urllib.parse import quote

import requests

import config

API_URL = config.S2_PAPER_BASE + "{}"
S2_UNAUTH_REQUEST_DELAY = 3.1  # giây: giữ dưới 100 request trong mọi khoảng 5 phút

FIELDS = ",".join([
    "references.title",
    "references.authors",
    "references.year",
    "references.publicationDate",
    "references.venue",
    "references.externalIds",
    "references.paperId",
])


class SemanticScholarError(Exception):
    """Lỗi API sau khi đã áp dụng chính sách retry."""

    error_type = "api_error"


class PaperNotIndexedError(SemanticScholarError):
    """Semantic Scholar không tìm thấy bài arXiv này."""

    error_type = "not_indexed"


class RateLimitError(SemanticScholarError):
    """Vẫn gặp HTTP 429 sau khi đã dùng hết số lần retry."""

    error_type = "rate_limited"


_request_lock = threading.Lock()
_last_request_at = 0.0
_session = requests.Session()


def _notify_attempt(
    callback: Callable[[dict[str, Any]], None] | None,
    *,
    arxiv_id: str,
    attempt: int,
    seconds: float,
    status: str,
    error_type: str = "",
    n_total: int | None = None,
    n_with_arxiv: int | None = None,
) -> None:
    if callback is not None:
        callback({
            "arxiv_id": arxiv_id,
            "attempt": attempt,
            "seconds": seconds,
            "status": status,
            "error_type": error_type,
            "n_total": n_total,
            "n_with_arxiv": n_with_arxiv,
        })


def _retry_after_seconds(value: str | None, attempt: int) -> float:
    """Đọc Retry-After; nếu thiếu thì dùng exponential backoff tối đa 60 giây."""
    if value:
        try:
            return max(0.0, float(value))
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(value)
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=timezone.utc)
                return max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())
            except (TypeError, ValueError, OverflowError):
                pass
    return float(min(max(5.0, 2.0 ** (attempt + 1)), 60.0))


def _wait_for_request_slot(delay: float) -> None:
    """Đảm bảo khoảng cách tối thiểu giữa thời điểm bắt đầu các request."""
    global _last_request_at
    remaining = delay - (time.monotonic() - _last_request_at)
    if remaining > 0:
        time.sleep(remaining)
    _last_request_at = time.monotonic()


def _with_arxiv_id(reference: dict[str, Any]) -> bool:
    external_ids = reference.get("externalIds") or {}
    return bool(
        external_ids.get("ArXiv")
        or external_ids.get("ArXivID")
        or external_ids.get("arXiv")
    )


def get_references(
    arxiv_id: str,
    *,
    on_attempt: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    """Lấy references cho một arXiv ID. """
    arxiv_id = arxiv_id.strip()
    if arxiv_id.lower().startswith("arxiv:"):
        arxiv_id = arxiv_id[6:]
    arxiv_id = config.strip_version(arxiv_id)
    if not arxiv_id:
        raise ValueError("arXiv ID không được để trống")

    api_key = (os.getenv("SEMANTIC_SCHOLAR_API_KEY") or "").strip()
    headers = {"User-Agent": config.USER_AGENT}
    if api_key:
        headers["x-api-key"] = api_key
    delay = (
        config.S2_REQUEST_DELAY
        if api_key
        else max(config.S2_REQUEST_DELAY, S2_UNAUTH_REQUEST_DELAY)
    )
    # API_URL đã có tiền tố arXiv:. Encode slash ở ID cũ thành một segment.
    paper_id = quote(arxiv_id, safe="")
    url = API_URL.format(paper_id)
    last_error: Exception | None = None

    # Khóa toàn bộ chu trình (pacing + request + retry), để cả các caller
    # đồng thời trong cùng process cũng không tạo request chồng nhau.
    with _request_lock:
        for attempt in range(1, config.MAX_RETRIES + 2):
            _wait_for_request_slot(delay)
            started = time.monotonic()
            try:
                response = _session.get(
                    url,
                    params={"fields": FIELDS},
                    headers=headers,
                    timeout=config.HTTP_TIMEOUT,
                )
            except (requests.Timeout, requests.ConnectionError) as exc:
                seconds = time.monotonic() - started
                last_error = exc
                error_type = type(exc).__name__.lower()
                _notify_attempt(
                    on_attempt, arxiv_id=arxiv_id, attempt=attempt,
                    seconds=seconds, status="fail", error_type=error_type,
                )
                if attempt > config.MAX_RETRIES:
                    raise SemanticScholarError(
                        f"Không gọi được Semantic Scholar cho {arxiv_id} "
                        f"sau {attempt} lần: {error_type}"
                    ) from exc
                time.sleep(float(min(2 ** attempt, 60)))
                continue

            seconds = time.monotonic() - started
            code = response.status_code

            if code == 404:
                _notify_attempt(
                    on_attempt, arxiv_id=arxiv_id, attempt=attempt,
                    seconds=seconds, status="empty", error_type="not_indexed",
                    n_total=0, n_with_arxiv=0,
                )
                raise PaperNotIndexedError(f"Không tìm thấy {arxiv_id} trên Semantic Scholar")

            if code == 429 or 500 <= code < 600:
                if code == 429:
                    error_type = "rate_limited"
                else:
                    error_type = f"http_{code}"
                _notify_attempt(
                    on_attempt, arxiv_id=arxiv_id, attempt=attempt,
                    seconds=seconds, status="fail", error_type=error_type,
                )
                if attempt > config.MAX_RETRIES:
                    message = f"Semantic Scholar trả HTTP {code} cho {arxiv_id} sau {attempt} lần"
                    if code == 429:
                        raise RateLimitError(message)
                    raise SemanticScholarError(message)
                time.sleep(_retry_after_seconds(response.headers.get("Retry-After"), attempt))
                continue

            if code < 200 or code >= 300:
                error_type = f"http_{code}"
                _notify_attempt(
                    on_attempt, arxiv_id=arxiv_id, attempt=attempt,
                    seconds=seconds, status="fail", error_type=error_type,
                )
                raise SemanticScholarError(
                    f"Semantic Scholar trả HTTP {code} cho {arxiv_id}"
                )

            try:
                paper_data = response.json()
            except ValueError as exc:
                _notify_attempt(
                    on_attempt, arxiv_id=arxiv_id, attempt=attempt,
                    seconds=seconds, status="fail", error_type="invalid_json",
                )
                raise SemanticScholarError(
                    f"Semantic Scholar trả JSON không hợp lệ cho {arxiv_id}"
                ) from exc

            references = paper_data.get("references") or []
            _notify_attempt(
                on_attempt, arxiv_id=arxiv_id, attempt=attempt,
                seconds=seconds, status="ok", n_total=len(references),
                n_with_arxiv=sum(_with_arxiv_id(ref) for ref in references),
            )
            return references

    # Vòng lặp luôn return hoặc raise; nhánh này chỉ để thỏa mãn type checker.
    raise SemanticScholarError(f"Không lấy được references cho {arxiv_id}") from last_error


if __name__ == "__main__":
    from reference_builder import main

    main()
