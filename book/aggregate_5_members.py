"""
aggregate_5_members.py — Gộp log của 5 thành viên thành số liệu TOÀN NHÓM (25.000 bài)

CÁCH DÙNG CHO TUẤN
------------------
1. Đặt file này vào thư mục gốc repo book (cùng cấp với _config.yml).
2. Đặt 9 file còn thiếu vào book/data/ theo ĐÚNG TÊN ở bảng MEMBERS bên dưới.
3. Chạy kiểm tra trước:   python aggregate_5_members.py
   -> in ra bảng từng thành viên + tổng nhóm, và báo file nào còn thiếu.
4. Khi đã đủ, copy phần hàm load_group() + bảng MEMBERS vào cell nạp dữ liệu
   của 02-statistics.ipynb, thay cho 4 dòng pd.read_csv hiện tại.

THIẾT KẾ
--------
- Thiếu file nào thì BỎ QUA file đó và vẫn chạy được -> Tuấn có thể cắm dần
  từng file khi thành viên gửi về, không phải chờ đủ 9 file mới chạy.
- Mỗi DataFrame được thêm cột `member` và `id_range` để vẽ biểu đồ so sánh
  giữa 5 người, và để chứng minh với người chấm là đủ 25.000 bài.
- Dedup theo (arxiv_id, version) giữ dòng CUỐI: một dòng = một lần thử, retry
  ghi thêm dòng mới (theo docs/schema.md), nên trạng thái cuối mới là kết quả.
"""

from pathlib import Path
import sys
import pandas as pd

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# ----------------------------------------------------------------------
# BẢNG TÊN FILE — 5 thành viên x 4 giai đoạn
# Ô nào là file CHƯA CÓ thì thành viên đó phải gửi về đúng tên này.
# ----------------------------------------------------------------------
MEMBERS = {
    "Anh Tuấn 24120153": {
        "id_range":   "2504.07523-2504.12522",
        "discovery":  "discovery.csv",          # đã có
        "download":   "download.csv",           # đã có
        "extract":    "extract.csv",            # đã có
        "references": "references.csv",         # đã có
    },
    "Ngọc Hoàng 24120053": {
        "id_range":   "2507.06659-2507.11658",
        "discovery":  "hoang_discovery.csv",    # đã có
        "download":   "hoang_download.csv",     # đã có
        "extract":    "hoang_extract.csv",      # đã có
        "references": "hoang_references.csv",   # đã có
    },
    "Minh Thư 24120144": {
        "id_range":   "2505.00666-2505.05665",
        "discovery":  "thu_discovery.csv",      # <-- THIẾU
        "download":   "thu_download.csv",       # đã có
        "extract":    "thu_extract.csv",        # <-- THIẾU
        "references": "thu_references.csv",     # <-- THIẾU
    },
    "Thanh Tú 24120152": {
        "id_range":   "2504.12523-2504.17522",
        "discovery":  "tu_discovery.csv",       # <-- THIẾU
        "download":   "tu_download.csv",        # <-- THIẾU
        "extract":    "tu_extract.csv",         # đã có
        "references": "tu_references.csv",      # <-- THIẾU
    },
    "Hửu Duy 24120177": {
        "id_range":   "2503.11914-2503.16913",
        "discovery":  "duy2_discovery.csv",     # <-- THIẾU
        "download":   "duy2_download.csv",      # <-- THIẾU
        "extract":    "duy2_extract.csv",       # <-- THIẾU
        "references": "duy2_references_clean.csv",  # đã có
    },
}

STAGE_KEYS = ("discovery", "download", "extract", "references")


def load_group(data_dir="data", verbose=True):
    """Trả về dict {stage: DataFrame gộp 5 người} + danh sách file thiếu."""
    data_dir = Path(data_dir)
    frames = {s: [] for s in STAGE_KEYS}
    missing = []

    for member, cfg in MEMBERS.items():
        for stage in STAGE_KEYS:
            fname = cfg[stage]
            path = data_dir / fname
            if not path.exists():
                missing.append((member, stage, fname))
                continue
            df = pd.read_csv(path, dtype={"arxiv_id": str}, low_memory=False)
            df["member"] = member
            df["id_range"] = cfg["id_range"]
            frames[stage].append(df)

    out = {}
    for stage, lst in frames.items():
        out[stage] = (pd.concat(lst, ignore_index=True) if lst
                      else pd.DataFrame(columns=["arxiv_id", "status", "member"]))

    if verbose and missing:
        print("THIẾU FILE (bỏ qua, vẫn chạy được):")
        for m, s, f in missing:
            print(f"   - {m:22} {s:11} -> cần file  data/{f}")
        print()

    return out, missing


def dedup_final(df, keys):
    """Giữ lần thử CUỐI của mỗi khóa — đó là trạng thái kết quả."""
    keys = [k for k in keys if k in df.columns]
    return df.groupby(keys, as_index=False).tail(1) if keys else df


def per_member_table(g):
    """Bảng số liệu từng thành viên — dùng trực tiếp làm bảng trong báo cáo."""
    rows = []
    for member, cfg in MEMBERS.items():
        r = {"Thành viên": member, "Dải ID": cfg["id_range"]}

        d = g["discovery"]
        d = d[d.member == member] if "member" in d.columns else d.iloc[0:0]
        # ĐẾM BÀI, KHÔNG ĐẾM DÒNG: một bài retry nhiều lần vẫn chỉ là 1 bài.
        r["Bài discovery ok"] = int(d[d.status == "ok"].arxiv_id.nunique()) if len(d) else 0

        dl = g["download"]
        dl = dl[dl.member == member] if "member" in dl.columns else dl.iloc[0:0]
        dlf = dedup_final(dl, ["arxiv_id", "version"])
        r["Version tải"] = len(dlf)
        r["Version ok"] = int((dlf.status == "ok").sum()) if len(dlf) else 0

        ex = g["extract"]
        ex = ex[ex.member == member] if "member" in ex.columns else ex.iloc[0:0]
        exf = dedup_final(ex, ["arxiv_id", "version"])
        exo = exf[exf.status == "ok"] if len(exf) else exf
        r["Version giải nén ok"] = len(exo)
        if len(exo) and "bytes_before" in exo.columns:
            before = pd.to_numeric(exo.bytes_before, errors="coerce").sum()
            after = pd.to_numeric(exo.bytes_after, errors="coerce").sum()
            r["Giảm dung lượng %"] = round((1 - after / before) * 100, 2) if before else 0
            r["Output MiB"] = round(after / 1024 / 1024, 1)
        else:
            r["Giảm dung lượng %"] = 0
            r["Output MiB"] = 0

        rf = g["references"]
        rf = rf[rf.member == member] if "member" in rf.columns else rf.iloc[0:0]
        if len(rf) and "arxiv_id" in rf.columns:
            rf = rf[~rf.arxiv_id.str.startswith("batch:")]
        rff = dedup_final(rf, ["arxiv_id"])
        rfo = rff[rff.status.isin(["ok", "skipped"])] if len(rff) else rff
        r["Bài có reference"] = rfo.arxiv_id.nunique() if len(rfo) else 0
        if len(rfo) and "n_total" in rfo.columns:
            nt = pd.to_numeric(rfo.n_total, errors="coerce")
            na = pd.to_numeric(rfo.n_with_arxiv, errors="coerce")
            r["Ref TB/bài"] = round(nt.mean(), 2)
            r["Matching pool"] = int(na.sum())
        else:
            r["Ref TB/bài"] = 0
            r["Matching pool"] = 0

        rows.append(r)
    return pd.DataFrame(rows)


def group_totals(g):
    """Con số TOÀN NHÓM — đây là phần làm báo cáo đạt 25.000 bài."""
    disc = g["discovery"]
    dlf = dedup_final(g["download"], ["arxiv_id", "version"])
    exf = dedup_final(g["extract"], ["arxiv_id", "version"])
    exo = exf[exf.status == "ok"] if len(exf) else exf
    rf = g["references"]
    if len(rf) and "arxiv_id" in rf.columns:
        rf = rf[~rf.arxiv_id.str.startswith("batch:")]
    rff = dedup_final(rf, ["member", "arxiv_id"])
    rfo = rff[rff.status.isin(["ok", "skipped"])] if len(rff) else rff

    before = pd.to_numeric(exo.get("bytes_before"), errors="coerce").sum() if len(exo) else 0
    after = pd.to_numeric(exo.get("bytes_after"), errors="coerce").sum() if len(exo) else 0
    na = pd.to_numeric(rfo.get("n_with_arxiv"), errors="coerce").sum() if len(rfo) else 0
    nt = pd.to_numeric(rfo.get("n_total"), errors="coerce") if len(rfo) else pd.Series(dtype=float)

    return {
        "Tổng bài được phân công": sum(1 for _ in MEMBERS) * 5000,
        "Bài discovery thành công": int(disc[disc.status == "ok"].arxiv_id.nunique()) if len(disc) else 0,
        "Tổng version tải về": len(dlf),
        "Version tải ok": int((dlf.status == "ok").sum()) if len(dlf) else 0,
        "Version có TeX giải nén ok": len(exo),
        "Giảm dung lượng toàn nhóm %": round((1 - after / before) * 100, 2) if before else 0,
        "Tổng output cuối (GiB)": round(after / 1024**3, 3),
        "Bài có reference": int(rfo.arxiv_id.nunique()) if len(rfo) else 0,
        "Reference TB/bài": round(nt.mean(), 2) if len(nt) else 0,
        "Tổng matching pool": int(na),
    }


# ______________________________________________________________________________
# PHẦN 2 — DỮ LIỆU NHÓM VIỆC NÂNG CAO
# 19 file dưới đây đang nằm trong data/ mà KHÔNG notebook nào đọc.
# Đây là phần việc nâng cao đã được giao và đã làm xong, nếu không đưa vào
# báo cáo thì công của 4 người thành vô hình với người chấm.
# ______________________________________________________________________________
ENHANCEMENTS = {
    "A1 — Tối ưu hiệu năng (Minh Thư)": {
        "owner": "Minh Thư 24120144",
        "files": ["thu_before_download.csv", "thu_after_download.csv",
                  "thu_before_extract.csv", "thu_after_extract.csv",
                  "before_after.md", "thu_error_analysis.md", "thu_report.txt"],
        "đã dùng": ["thu_runs.csv", "thu_summary.json"],
    },
    "A2 — Data Validation Suite (Thanh Tú)": {
        "owner": "Thanh Tú 24120152",
        "files": ["tu_validation.txt"],
        "đã dùng": [],
    },
    "A3 — Cross-validation 3 nguồn (Ngọc Hoàng)": {
        "owner": "Ngọc Hoàng 24120053",
        "files": ["a3_field_agreement.csv", "a3_disagreements.csv",
                  "a3_api_recheck.csv", "a3_cross_validation.md",
                  "a3_cross_validation_docs.md"],
        "đã dùng": ["a3_coverage.csv", "a3_three_way.csv",
                    "a3_versions.csv", "a3_author_causes.csv"],
    },
    "C — Tiền xử lý bắc cầu M2/M3 (Hửu Duy)": {
        "owner": "Hửu Duy 24120177",
        "files": ["duy2_prescan_versions.csv", "duy2_prescan_summary.json",
                  "duy2_ReadMe.txt", "duy_report.md"],
        "đã dùng": [],
    },
}

# File KHÔNG ĐƯỢC dùng: bản crawl cũ còn lẫn 75 dòng ID 2502.* ngoài phạm vi.
# Đã bị thay bằng duy2_references_clean.csv. Nên xoá khỏi data/ để không ai
# đọc nhầm, và để người chấm không thấy hai file references của cùng một người.
DO_NOT_USE = ["duy_references.csv"]


def load_a1_before_after(data_dir="data"):
    """A1 của Thư: so sánh trước/sau tối ưu, tính TỪ FILE thay vì gõ tay.

    CẢNH BÁO đã kiểm thực nghiệm: KHÔNG lấy cột `seconds` của
    thu_before/after_download.csv làm thời gian. Cột đó là thời gian mỗi
    request, không gồm 3 s pacing — tổng chỉ ra 5,67 s / 6,28 s, trong khi
    wall-clock thật là ~103 s. Wall-clock và dung lượng đĩa nằm ở
    `thu_runs.csv`, phân biệt bằng cột `disk_scope` (delta:before / delta:after).
    Cách tính dưới đây tái lập đúng 96,8 MB -> 5,8 MB như `before_after.md`.
    """
    data_dir = Path(data_dir)
    runs = data_dir / "thu_runs.csv"
    if not runs.exists():
        return pd.DataFrame()
    r = pd.read_csv(runs)
    wall = pd.to_numeric(r.wall_time_seconds, errors="coerce")
    disk = pd.to_numeric(r.disk_usage_mb, errors="coerce")
    ram = pd.to_numeric(r.peak_ram_mb, errors="coerce")

    out = {}
    for side, tag in (("before", "delta:before"), ("after", "delta:after")):
        m = r.disk_scope == tag
        if not m.any():
            continue
        out[side] = {
            "Số run": int(m.sum()),
            "Wall-clock (s)": round(wall[m].sum(), 2),
            "Đĩa tăng thêm (MB)": round(disk[m].sum(), 2),
            "RAM đỉnh (MB)": round(ram[m].max(), 2),
        }

    # Số version và mức giảm dung lượng lấy từ cặp file before/after
    for side in ("before", "after"):
        ex = data_dir / f"thu_{side}_extract.csv"
        if side in out and ex.exists():
            e = pd.read_csv(ex, dtype={"arxiv_id": str})
            bb = pd.to_numeric(e.get("bytes_before"), errors="coerce").sum()
            ba = pd.to_numeric(e.get("bytes_after"), errors="coerce").sum()
            out[side]["Version extract"] = len(e)
            out[side]["Giảm dung lượng %"] = round((1 - ba / bb) * 100, 2) if bb else 0

    df = pd.DataFrame(out).T if out else pd.DataFrame()
    # Hàng "thay đổi" phải là chuỗi %, nên ép cả bảng về object trước khi gán,
    # không thì pandas báo TypeError vì cột đang là float64.
    if {"before", "after"} <= set(df.index):
        df = df.astype(object)
        for col in df.columns:
            b, a = df.loc["before", col], df.loc["after", col]
            try:
                df.loc["thay đổi", col] = f"{(a / b - 1) * 100:+.1f}%" if b else "-"
            except (TypeError, ZeroDivisionError):
                df.loc["thay đổi", col] = "-"
    return df


def load_prescan(data_dir="data"):
    """Nhóm việc C của Duy: thống kê TeX/bib, tính TỪ FILE thay vì gõ tay.

    CẢNH BÁO đã kiểm thực nghiệm: matching_pool_size phải gộp THEO BÀI,
    không được sum trên 8.129 version — sum theo version ra 190.813 vì bài
    nhiều version bị đếm trùng. Gộp max theo arxiv_id ra đúng 106.352,
    khớp từng con số với duy2_ReadMe.txt (TB 21,27 · trung vị 13 · max 4.331).
    """
    p = Path(data_dir) / "duy2_prescan_versions.csv"
    if not p.exists():
        return None
    pv = pd.read_csv(p, dtype={"arxiv_id": str}, low_memory=False)
    has_tex = pv.has_tex.astype(str).str.lower().eq("true")
    ntex = pd.to_numeric(pv.n_tex_files, errors="coerce")
    nbib = pd.to_numeric(pv.n_bibitem, errors="coerce")
    pool_per_paper = (pv.assign(_p=pd.to_numeric(pv.matching_pool_size, errors="coerce"))
                        .groupby("arxiv_id")._p.max())
    return {
        "Tổng version quét": len(pv),
        "Version có TeX": int(has_tex.sum()),
        "Tổng file .tex": int(ntex.sum()),
        "File .tex TB/version có TeX": round(ntex[has_tex].mean(), 2),
        "Tỉ lệ dò được root %": round(pv.root_file.notna().sum() / max(has_tex.sum(), 1) * 100, 2),
        "Tổng \\bibitem inline": int(nbib.sum()),
        "Phân bố bib_style": dict(pv.bib_style.value_counts()),
        "Matching pool (gộp theo bài)": int(pool_per_paper.sum()),
        "Matching pool TB/bài": round(pool_per_paper.mean(), 2),
        "Matching pool trung vị/max": f"{pool_per_paper.median():.0f} / {pool_per_paper.max():.0f}",
    }


def load_a3_extra(data_dir="data"):
    """A3 của Hoàng: 3 bảng chi tiết chưa được book đọc."""
    data_dir = Path(data_dir)
    out = {}
    for key, fname in (("field_agreement", "a3_field_agreement.csv"),
                       ("disagreements", "a3_disagreements.csv"),
                       ("api_recheck", "a3_api_recheck.csv")):
        p = data_dir / fname
        if p.exists():
            out[key] = pd.read_csv(p, dtype=str, low_memory=False)
    return out


def enhancement_audit(data_dir="data"):
    """In ra file nâng cao nào đã có, file nào thiếu — để không bỏ sót ai."""
    data_dir = Path(data_dir)
    print(f"{'NHÓM VIỆC':44}{'ĐÃ DÙNG':>10}{'CHƯA DÙNG':>12}")
    print("-" * 78)
    for name, cfg in ENHANCEMENTS.items():
        have = [f for f in cfg["files"] if (data_dir / f).exists()]
        print(f"{name:44}{len(cfg['đã dùng']):>10}{len(have):>12}")
        for f in have:
            print(f"      chưa đọc: {f}")
    for f in DO_NOT_USE:
        if (data_dir / f).exists():
            print(f"\n  ⚠ XOÁ FILE NÀY: {f} (bản cũ còn lẫn ID 2502.*, đã bị thay thế)")


if __name__ == "__main__":
    g, missing = load_group("data")

    print("=" * 78)
    print("BẢNG TỪNG THÀNH VIÊN")
    print("=" * 78)
    print(per_member_table(g).to_string(index=False))

    print()
    print("=" * 78)
    print("TỔNG TOÀN NHÓM")
    print("=" * 78)
    for k, v in group_totals(g).items():
        print(f"  {k:32} {v:,}" if isinstance(v, int) else f"  {k:32} {v}")

    print()
    if missing:
        print(f">> Còn thiếu {len(missing)} file. Số trên là của phần đã có.")
    else:
        print(">> ĐỦ 20/20 file. Số trên là số liệu toàn nhóm 25.000 bài.")

    print()
    print("=" * 78)
    print("PHẦN 2 — NHÓM VIỆC NÂNG CAO (file đang có mà book chưa đọc)")
    print("=" * 78)
    enhancement_audit("data")

    ba = load_a1_before_after("data")
    if len(ba):
        print("\n--- A1 Minh Thư: trước/sau tối ưu (tính từ file) ---")
        print(ba.to_string())

    ps = load_prescan("data")
    if ps:
        print("\n--- C Hửu Duy: prescan TeX/bib (tính từ file) ---")
        for k, v in ps.items():
            print(f"  {k:32} {v}")

    a3 = load_a3_extra("data")
    if a3:
        print("\n--- A3 Ngọc Hoàng: 3 bảng chi tiết chưa được book đọc ---")
        for k, df in a3.items():
            print(f"  {k:18} {len(df):>5} dòng · cột: {list(df.columns)}")
