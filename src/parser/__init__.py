"""Package parser của Milestone 2 — Hierarchical Parsing & Standardization.

Thứ tự chạy pipeline (xem docs/schema_m2.md mục 5):

    1. gather.gather()                  — Minh Thư
    2. normalize.clean_latex/_math      — Thanh Tú
    3. bib_dedup.unify_publication()    — Hửu Duy (hai lượt)
    4. elements.build_store()           — Nhóm trưởng

Mọi module đọc/ghi theo đúng docs/schema_m2.md. Muốn đổi một trường → báo nhóm trước.
"""

__all__ = ["gather", "normalize", "bib", "bib_dedup", "hierarchy", "elements"]
