"""Chuẩn hoá LaTeX và chuẩn hoá công thức toán.

⚠️ MODULE NÀY QUYẾT ĐỊNH DEDUP CỦA CẢ NHÓM.

element_id được băm từ ĐẦU RA của module này (docs/schema_m2.md mục 2). Chuẩn hoá yếu
thì hai câu giống nhau ở v1 và v2 chỉ khác một dấu cách sẽ thành hai element khác nhau,
và dedup thất bại.

Hệ quả về lịch: quy tắc chuẩn hoá ĐÓNG BĂNG TỪ 11/11. Sau ngày đó không sửa nữa,
vì sửa là toàn bộ element_id đổi theo và phải parse lại từ đầu.
"""

from __future__ import annotations


def clean_latex(s: str) -> str:
    """Bỏ lệnh định dạng không mang nghĩa, giữ nội dung ngữ nghĩa.

    Bỏ      : \\centering, \\raggedright, \\midrule, \\toprule, \\hline, \\vspace{...},
              tuỳ chọn vị trí [htbp] sau \\begin{figure}/{table}
    Giữ ruột: \\textbf{x} -> x, \\emph{x} -> x, \\texttt{x} -> x
    Gộp     : mọi chuỗi khoảng trắng về đúng một dấu cách  (BẮT BUỘC cho dedup)

    GIỮ NGUYÊN \\includegraphics và môi trường figure — đề Milestone 1 đã yêu cầu,
    Milestone 2 không đổi.

    Bất biến bắt buộc: clean_latex(clean_latex(x)) == clean_latex(x)
    """
    raise NotImplementedError


def normalize_math(s: str) -> str:
    """Đưa mọi công thức về một dạng thống nhất.

    Khối : $$...$$, \\[...\\], equation*, align, align*, gather, eqnarray, displaymath
           -> \\begin{equation}...\\end{equation}
    Inline: \\(...\\)  -> $...$

    ⚠️ XỬ LÝ KHỐI TRƯỚC, INLINE SAU. Làm ngược thì $$x$$ bị cắt thành $ + $x$ + $.

    Bất biến bắt buộc: normalize_math(normalize_math(x)) == normalize_math(x)
    """
    raise NotImplementedError
