"""Khử trùng lặp reference xuyên version: gộp trường và đổi tên \\cite.

Đề yêu cầu ba vế (docs/schema_m2.md mục 5):
    (1) chọn MỘT citation key chuẩn
    (2) đổi tên mọi \\cite{} của các key bị loại sang key đã chọn
    (3) HỢP NHẤT các trường, không được chọn một entry rồi vứt phần còn lại

Ví dụ của đề:
    v1  vaswani2017      title, author, year
    v2  vit_transformer  title, author, doi
    v3  vit_transformer  title, author          (mất year)
    -> một entry, một key, trường = title + author + year + doi
"""

from __future__ import annotations

from typing import Any


def signature(entry: dict[str, Any]) -> str:
    """Chữ ký nhận ra hai entry là cùng một tài liệu.

    Ưu tiên: doi > arxiv_id > (tiêu đề chuẩn hoá + họ tác giả đầu).

    ⚠️ KHÔNG đưa `year` vào chữ ký — chính ví dụ của đề có v3 bị mất year.
    ⚠️ Gom nhóm phải BẮC CẦU: v1 nối v3 qua tiêu đề, v2 có doi nên chữ ký khác hẳn.
       Mỗi entry sinh nhiều khoá; hai entry chung bất kỳ khoá nào thì nhập một nhóm.
    """
    raise NotImplementedError


def merge_group(entries: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, str]]:
    """Gộp một nhóm entry trùng nhau.

    Chọn key chuẩn TẤT ĐỊNH: version nhỏ nhất trước -> key ngắn hơn -> thứ tự chữ cái.
    Chạy lại phải ra cùng kết quả, không phụ thuộc thứ tự duyệt dict.

    Returns:
        (entry đã gộp trường, {key_cũ: key_chuẩn})
    """
    raise NotImplementedError


def rename_cites(tex: str, rename: dict[str, str]) -> str:
    """Đổi tên citation key trong chính văn bản.

    Bắt \\cite, \\citep, \\citet, \\citeyear, \\citealp, có cả dạng \\cite[tr.5]{key}.
    Nhiều key trong một lệnh: đổi tên xong thì SORT và bỏ trùng
    -> \\cite{b,a} và \\cite{a,b} ra cùng kết quả, nếu không thì băm ra hai id khác nhau.
    Key không tồn tại (dangling): giữ nguyên, đếm lại để báo cáo.
    """
    raise NotImplementedError


def unify_publication(
    norm_text: dict[int, str],
    bib_entries: dict[int, list[dict[str, Any]]],
) -> tuple[dict[int, str], list[dict[str, Any]], dict[str, str]]:
    """HÀM DUY NHẤT MÀ NHÓM TRƯỞNG GỌI. Chạy hai lượt.

    Lượt 1: đọc bib của TẤT CẢ version -> gom nhóm -> dựng rename_map
    Lượt 2: áp rename_cites() lên văn bản đã chuẩn hoá của từng version

    Phải hai lượt vì rename_map chỉ dựng được khi đã thấy hết mọi version.

    Args:
        norm_text:   {version: toàn văn đã chuẩn hoá (bước 2 của pipeline)}
        bib_entries: {version: entry từ .bib và \\bibitem}

    Returns:
        (renamed_text, bibtex_rows, rename_map)

    HẠN GIAO CHO NHÓM TRƯỞNG: 17/11.
    """
    raise NotImplementedError
