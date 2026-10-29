"""
config.py — Hằng số và tiện ích dùng chung cho toàn bộ pipeline Milestone 1.

MỌI module của nhóm import từ đây. Không ai hardcode URL, delay hay đường dẫn
trong file riêng của mình — đổi một chỗ là cả pipeline đổi theo.

Căn cứ từ đề bài (crawling.md):
  - "wait at least 3 seconds between successive calls and use one connection at a time"
  - "Point automated downloads at this mirror and never at the main site arxiv.org"
  - "use a descriptive User-Agent header"
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ----------------------------------------------------------------------
# Nhận dạng nhóm — SỬA 2 DÒNG NÀY cho đúng nhóm mình
# ----------------------------------------------------------------------
GROUP_NAME = "IntroDS-Group-04"
CONTACT_EMAIL = "24120053@student.hcmus.edu.vn"

USER_AGENT = f"{GROUP_NAME}/1.0 (academic course project; mailto:{CONTACT_EMAIL})"

# ----------------------------------------------------------------------
# Endpoint
# ----------------------------------------------------------------------
# Mirror dành riêng cho tải source. KHÔNG BAO GIỜ trỏ về https://arxiv.org/
ARXIV_SRC_BASE = "https://export.arxiv.org/src/"

# Semantic Scholar (Hữu Duy dùng)
S2_PAPER_BASE = "https://api.semanticscholar.org/graph/v1/paper/arXiv:"
S2_BATCH_URL = "https://api.semanticscholar.org/graph/v1/paper/batch"

# OAI-PMH — endpoint MỚI từ tháng 3/2025 (địa chỉ cũ export.arxiv.org/oai2 đã khai tử)
OAI_PMH_ENDPOINT = "https://oaipmh.arxiv.org/oai"

# ----------------------------------------------------------------------
# Pacing — ràng buộc cứng, không ai được giảm
# ----------------------------------------------------------------------
REQUEST_DELAY = 3.0        # giây, giữa 2 request tới arXiv
S2_REQUEST_DELAY = 1.1     # giây, Semantic Scholar cho 1 req/s -> để dư 0.1s
HTTP_TIMEOUT = 60          # giây
MAX_RETRIES = 4            # số lần thử lại khi 429/5xx

# ----------------------------------------------------------------------
# Đường dẫn (ghi đè được bằng biến môi trường, tiện khi chạy trên Colab)
# ----------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent

CORPUS_ROOT = Path(os.environ.get("CORPUS_ROOT", PROJECT_ROOT / "corpus"))
LOGS_ROOT = Path(os.environ.get("LOGS_ROOT", PROJECT_ROOT / "logs"))
IDS_ROOT = Path(os.environ.get("IDS_ROOT", PROJECT_ROOT / "ids"))
REPORTS_ROOT = Path(os.environ.get("REPORTS_ROOT", PROJECT_ROOT / "reports"))

# Múi giờ của nhóm, dùng cho các mốc thời gian ghi vào file
LOCAL_TZ = timezone(timedelta(hours=7))  # Asia/Saigon

# ----------------------------------------------------------------------
# Loại file được giữ lại trong corpus
# Đề: "extract only the .tex and .bib files"
# ----------------------------------------------------------------------
KEEP_EXTENSIONS = (".tex", ".bib")

# Giá trị hợp lệ của trường `reason` trong _EMPTY.json (xem docs/schema.md)
EMPTY_REASONS = (
    "pdf_only",
    "docx_only",
    "no_tex_in_archive",
    "http_403",
    "http_404",
    "timeout",
    "corrupt_archive",
    "other",
)


# ----------------------------------------------------------------------
# Tiện ích dùng chung
# ----------------------------------------------------------------------
def pub_key(arxiv_id: str) -> str:
    """Đổi arXiv ID thành tên thư mục an toàn trên mọi hệ điều hành.

    >>> pub_key("2310.12345")
    '2310-12345'
    >>> pub_key("hep-th/9901001")
    'hep-th_9901001'
    >>> pub_key("2310.12345v2")      # version suffix bị cắt bỏ
    '2310-12345'

    Lưu ý: giá trị `arxiv_id` ghi BÊN TRONG file JSON vẫn giữ nguyên bản gốc.
    Hàm này chỉ dùng để đặt tên thư mục.
    """
    base = strip_version(arxiv_id)
    return base.replace(".", "-").replace("/", "_")


def strip_version(arxiv_id: str) -> str:
    """Bỏ hậu tố version nếu có.

    >>> strip_version("2310.12345v4")
    '2310.12345'
    >>> strip_version("hep-th/9901001v2")
    'hep-th/9901001'
    """
    return re.sub(r"v\d+$", "", arxiv_id.strip())


def parse_version(versioned_id: str) -> int | None:
    """Đọc số version từ một ID có hậu tố.

    >>> parse_version("2310.12345v4")
    4
    >>> parse_version("2310.12345")      # không có hậu tố
    """
    m = re.search(r"v(\d+)$", versioned_id.strip())
    return int(m.group(1)) if m else None


def versioned_id(arxiv_id: str, version: int) -> str:
    """Ghép ID + version để gọi endpoint /src/.

    >>> versioned_id("2310.12345", 2)
    '2310.12345v2'
    """
    return f"{strip_version(arxiv_id)}v{int(version)}"


def src_url(arxiv_id: str, version: int) -> str:
    """URL tải source của MỘT version cụ thể."""
    return ARXIV_SRC_BASE + versioned_id(arxiv_id, version)


def pub_dir(arxiv_id: str) -> Path:
    """Thư mục làm việc của một publication."""
    return CORPUS_ROOT / pub_key(arxiv_id)


def version_dir(arxiv_id: str, version: int) -> Path:
    """Thư mục của một version."""
    return pub_dir(arxiv_id) / f"v{int(version)}"


def now_iso() -> str:
    """Thời điểm hiện tại, ISO 8601, giờ địa phương (+07:00)."""
    return datetime.now(LOCAL_TZ).isoformat(timespec="seconds")


def to_iso(dt: datetime | None) -> str | None:
    """Chuẩn hóa datetime của arxiv.py về chuỗi ISO 8601 UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat(timespec="seconds")


def ensure_dirs() -> None:
    """Tạo sẵn các thư mục gốc. Gọi một lần ở đầu mỗi script."""
    for d in (CORPUS_ROOT, LOGS_ROOT, IDS_ROOT, REPORTS_ROOT):
        d.mkdir(parents=True, exist_ok=True)


if __name__ == "__main__":
    import doctest

    failed, total = doctest.testmod()
    print(f"doctest: {total - failed}/{total} passed")
    print(f"USER_AGENT     = {USER_AGENT}")
    print(f"CORPUS_ROOT    = {CORPUS_ROOT}")
    print(f"src_url demo   = {src_url('2310.12345', 2)}")
    print(f"pub_key demo   = {pub_key('hep-th/9901001')}")
