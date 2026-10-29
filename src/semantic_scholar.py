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
BATCH_URL = config.S2_BATCH_URL
BATCH_MAX_IDS = 500  # giới hạn của POST /paper/batch
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


class ConnectionFailedError(SemanticScholarError):
    """Vẫn timeout hoặc lỗi kết nối sau khi đã dùng hết số lần retry."""

    error_type = "connection_failed"


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


def _normalize_id(arxiv_id: str) -> str:
    arxiv_id = arxiv_id.strip()
    if arxiv_id.lower().startswith("arxiv:"):
        arxiv_id = arxiv_id[6:]
    arxiv_id = config.strip_version(arxiv_id)
    if not arxiv_id:
        raise ValueError("arXiv ID không được để trống")
    return arxiv_id


def _auth() -> tuple[dict[str, str], float]:
    """Header và khoảng cách request, tùy có API key hay không."""
    api_key = (os.getenv("SEMANTIC_SCHOLAR_API_KEY") or "").strip()
    headers = {"User-Agent": config.USER_AGENT}
    if api_key:
        headers["x-api-key"] = api_key
    delay = (
        config.S2_REQUEST_DELAY
        if api_key
        else max(config.S2_REQUEST_DELAY, S2_UNAUTH_REQUEST_DELAY)
    )
    return headers, delay


def _send(
    method: str,
    url: str,
    *,
    label: str,
    on_attempt: Callable[[dict[str, Any]], None] | None,
    **kwargs: Any,
) -> tuple[requests.Response, int, float]:
    """Gửi request có pacing; retry khi timeout, 429 hoặc 5xx.

    Trả về (response, attempt, seconds) cho mọi mã khác 429/5xx để caller tự
    xử lý. Phải gọi bên trong ``_request_lock``.
    """
    headers, delay = _auth()
    for attempt in range(1, config.MAX_RETRIES + 2):
        _wait_for_request_slot(delay)
        started = time.monotonic()
        try:
            response = _session.request(
                method, url, headers=headers, timeout=config.HTTP_TIMEOUT, **kwargs,
            )
        except (requests.Timeout, requests.ConnectionError) as exc:
            seconds = time.monotonic() - started
            error_type = type(exc).__name__.lower()
            _notify_attempt(
                on_attempt, arxiv_id=label, attempt=attempt,
                seconds=seconds, status="fail", error_type=error_type,
            )
            if attempt > config.MAX_RETRIES:
                raise ConnectionFailedError(
                    f"Không gọi được Semantic Scholar cho {label} "
                    f"sau {attempt} lần: {error_type}"
                ) from exc
            time.sleep(float(min(2 ** attempt, 60)))
            continue

        seconds = time.monotonic() - started
        code = response.status_code
        if code == 429 or 500 <= code < 600:
            error_type = "rate_limited" if code == 429 else f"http_{code}"
            _notify_attempt(
                on_attempt, arxiv_id=label, attempt=attempt,
                seconds=seconds, status="fail", error_type=error_type,
            )
            if attempt > config.MAX_RETRIES:
                message = f"Semantic Scholar trả HTTP {code} cho {label} sau {attempt} lần"
                if code == 429:
                    raise RateLimitError(message)
                raise SemanticScholarError(message)
            time.sleep(_retry_after_seconds(response.headers.get("Retry-After"), attempt))
            continue
        return response, attempt, seconds

    # Vòng lặp luôn return hoặc raise; nhánh này chỉ để thỏa mãn type checker.
    raise SemanticScholarError(f"Không lấy được dữ liệu cho {label}")


def _parse_json(
    response: requests.Response,
    *,
    label: str,
    attempt: int,
    seconds: float,
    on_attempt: Callable[[dict[str, Any]], None] | None,
) -> Any:
    code = response.status_code
    if code < 200 or code >= 300:
        _notify_attempt(
            on_attempt, arxiv_id=label, attempt=attempt,
            seconds=seconds, status="fail", error_type=f"http_{code}",
        )
        raise SemanticScholarError(f"Semantic Scholar trả HTTP {code} cho {label}")
    try:
        return response.json()
    except ValueError as exc:
        _notify_attempt(
            on_attempt, arxiv_id=label, attempt=attempt,
            seconds=seconds, status="fail", error_type="invalid_json",
        )
        raise SemanticScholarError(
            f"Semantic Scholar trả JSON không hợp lệ cho {label}"
        ) from exc


def get_references(
    arxiv_id: str,
    *,
    on_attempt: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    """Lấy references cho một arXiv ID. """
    arxiv_id = _normalize_id(arxiv_id)
    # API_URL đã có tiền tố arXiv:. Encode slash ở ID cũ thành một segment.
    url = API_URL.format(quote(arxiv_id, safe=""))

    # Khóa toàn bộ chu trình (pacing + request + retry), để cả các caller
    # đồng thời trong cùng process cũng không tạo request chồng nhau.
    with _request_lock:
        response, attempt, seconds = _send(
            "GET", url, label=arxiv_id, on_attempt=on_attempt,
            params={"fields": FIELDS},
        )

    if response.status_code == 404:
        _notify_attempt(
            on_attempt, arxiv_id=arxiv_id, attempt=attempt,
            seconds=seconds, status="empty", error_type="not_indexed",
            n_total=0, n_with_arxiv=0,
        )
        raise PaperNotIndexedError(f"Không tìm thấy {arxiv_id} trên Semantic Scholar")

    paper_data = _parse_json(
        response, label=arxiv_id, attempt=attempt, seconds=seconds, on_attempt=on_attempt,
    )
    references = paper_data.get("references") or []
    _notify_attempt(
        on_attempt, arxiv_id=arxiv_id, attempt=attempt,
        seconds=seconds, status="ok", n_total=len(references),
        n_with_arxiv=sum(_with_arxiv_id(ref) for ref in references),
    )
    return references


def get_references_batch(
    arxiv_ids: list[str],
    *,
    on_attempt: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, list[dict[str, Any]] | None]:
    """Lấy references cho nhiều arXiv ID bằng một request POST /paper/batch.

    Trả về {arxiv_id: references}; giá trị None nghĩa là Semantic Scholar không
    lập chỉ mục bài đó. Kết quả mỗi bài giống hệt ``get_references``.
    """
    ids = list(dict.fromkeys(_normalize_id(arxiv_id) for arxiv_id in arxiv_ids))
    if not ids:
        return {}
    if len(ids) > BATCH_MAX_IDS:
        raise ValueError(f"Một lô tối đa {BATCH_MAX_IDS} ID, nhận {len(ids)}")
    label = f"batch:{ids[0]}..{ids[-1]}"

    with _request_lock:
        response, attempt, seconds = _send(
            "POST", BATCH_URL, label=label, on_attempt=on_attempt,
            params={"fields": FIELDS}, json={"ids": [f"arXiv:{i}" for i in ids]},
        )

    # Khi không ID nào trong lô có trên S2, API trả 400 thay vì list toàn null.
    if response.status_code == 400 and "No valid paper ids" in response.text:
        data: Any = [None] * len(ids)
    else:
        data = _parse_json(
            response, label=label, attempt=attempt, seconds=seconds, on_attempt=on_attempt,
        )
    if not isinstance(data, list) or len(data) != len(ids):
        _notify_attempt(
            on_attempt, arxiv_id=label, attempt=attempt,
            seconds=seconds, status="fail", error_type="invalid_json",
        )
        raise SemanticScholarError(f"Semantic Scholar trả kết quả lô không khớp cho {label}")

    # Chia đều thời gian request cho từng bài để log vẫn một dòng mỗi bài.
    per_paper = seconds / len(ids)
    result: dict[str, list[dict[str, Any]] | None] = {}
    for arxiv_id, paper in zip(ids, data):
        if paper is None:
            result[arxiv_id] = None
            _notify_attempt(
                on_attempt, arxiv_id=arxiv_id, attempt=attempt,
                seconds=per_paper, status="empty", error_type="not_indexed",
                n_total=0, n_with_arxiv=0,
            )
            continue
        references = paper.get("references") or []
        result[arxiv_id] = references
        _notify_attempt(
            on_attempt, arxiv_id=arxiv_id, attempt=attempt,
            seconds=per_paper, status="ok", n_total=len(references),
            n_with_arxiv=sum(_with_arxiv_id(ref) for ref in references),
        )
    return result


if __name__ == "__main__":
    from reference_builder import main

    main()
