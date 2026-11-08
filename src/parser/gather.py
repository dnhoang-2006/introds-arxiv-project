"""Multi-file Gathering — tìm đường biên dịch thật của một version.

Đề yêu cầu: chỉ parse những file thực sự được biên dịch vào PDF cuối, bỏ qua file thừa
nằm lẫn trong thư mục source. Theo \\input và \\include ĐỆ QUY, coi lệnh bị comment là
văn bản thường.

ĐÃ CÓ SẴN trong src/tex_prescan.py (Hửu Duy viết ở Milestone 1) — đọc trước khi code:
    DOC_CLASS_PATTERN   dòng 28   regex tìm \\documentclass / \\documentstyle
    INCLUDE_PATTERN     dòng 29   bắt \\input{}, \\include{}, \\subfile{}
    INPUT_BARE_PATTERN  dòng 30   bắt \\input path không ngoặc nhọn
    clean_tex_comments  dòng 35   bỏ comment
    extract_includes    dòng 52   trích include của MỘT file
    score_root_candidate dòng 68  chọn root khi có nhiều ứng viên

Việc còn thiếu: phần đệ quy (docstring của tex_prescan ghi rõ "chưa resolve đệ quy").
"""

from __future__ import annotations

from pathlib import Path


def resolve_path(base: Path, raw: str, vdir: Path) -> Path | None:
    """Đổi tham số của \\input/\\include thành đường dẫn file thật.

    LaTeX tự thêm đuôi .tex nếu thiếu, và tham số có thể tương đối với file cha
    hoặc với thư mục gốc của version.

    Args:
        base: thư mục chứa file đang chứa lệnh include
        raw:  chuỗi trong ngoặc, ví dụ "sections/intro" hoặc "intro.tex"
        vdir: thư mục gốc của version, ví dụ corpus/2310-12345/v1

    Returns:
        Path tuyệt đối đã resolve, hoặc None nếu không tìm thấy file.
    """
    raise NotImplementedError


def gather(vdir: Path) -> tuple[list[Path], list[Path]]:
    """Trả về (đường biên dịch theo thứ tự, danh sách file thừa).

    Bắt đầu từ root file (file chứa \\documentclass), đi đệ quy theo các lệnh
    include. File .tex nào trong vdir mà không nằm trong đường biên dịch thì là file thừa.

    Bốn ca phải xử lý:
        - Vòng lặp include (a gọi b, b gọi lại a)  -> dùng tập `seen`, không được treo
        - \\input trỏ vào file không tồn tại        -> bỏ qua, đếm vào n_missing_includes
        - Không tìm thấy root                       -> trả ([], mọi file .tex), log no_root
        - Version rỗng (có _EMPTY.json)             -> trả ([], []), log empty_version

    Returns:
        (compile_path, unused_files). compile_path rỗng nghĩa là không parse được.
    """
    raise NotImplementedError


def run(ids: list[str], limit: int | None = None) -> None:
    """Chạy gather cho nhiều publication và ghi logs/gather.csv.

    Định dạng cột xem docs/schema_m2.md mục 8.
    """
    raise NotImplementedError
