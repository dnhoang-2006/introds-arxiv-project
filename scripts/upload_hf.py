"""Đẩy dataset đã xuất lên Hugging Face Hub và in ra link để nộp.

    python src/export_hf.py  --mssv 24120053 --overwrite --shard-rows 500000
    python scripts/upload_hf.py --mssv 24120053

`export_hf.py` chỉ tạo Parquet cục bộ, không upload. Script này làm nốt phần còn
lại: tạo dataset repo nếu chưa có, đẩy cả thư mục `hf_export/<MSSV>` lên, rồi in
link. Mỗi thành viên tự host dataset của mình và tự nộp link riêng — thầy chốt ở
M3 câu 2 và câu 5.

Xác thực, chọn một trong hai:
    hf auth login                      # lưu token vào máy, làm một lần
    set HF_TOKEN=hf_xxx                # hoặc đặt biến môi trường (PowerShell: $env:HF_TOKEN)
Token phải là loại **write**, lấy ở https://huggingface.co/settings/tokens

Cần thêm vào src/requirements.txt:  huggingface_hub>=0.26
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PREFIX = "introds-arxiv"

#: File không bao giờ đẩy lên Hub.
IGNORE = ("*.tmp", ".*", "__pycache__/*")


def _die(msg: str) -> "typing.NoReturn":  # noqa: F821
    print(f"LỖI: {msg}", file=sys.stderr)
    raise SystemExit(1)


def _check_export(folder: Path, mssv: str) -> dict:
    """Kiểm thư mục export trước khi đẩy, và trả về manifest.

    Đẩy nhầm một thư mục dang dở lên Hub rồi mới phát hiện thì mất công xoá repo,
    nên thà dừng sớm.
    """
    if not folder.is_dir():
        _die(f"Chưa có {folder}. Chạy src/export_hf.py trước.")

    readme = folder / "README.md"
    if not readme.is_file():
        _die(f"Thiếu {readme}. Thư mục này không phải bản export hoàn chỉnh.")
    if "config_name:" not in readme.read_text(encoding="utf-8"):
        _die(f"{readme} thiếu khối YAML `configs`; Hugging Face sẽ không nhận ra các bảng.")

    manifest_path = folder / "metadata" / f"export-manifest-{mssv}.json"
    if not manifest_path.is_file():
        _die(f"Thiếu {manifest_path}. Chạy lại src/export_hf.py --overwrite.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    tables = sorted(p.name for p in (folder / "data").iterdir()) if (folder / "data").is_dir() else []
    missing = [t for t in ("papers", "references", "elements", "hierarchy", "bibtex") if t not in tables]
    if missing:
        _die(f"Thiếu bảng {', '.join(missing)} trong {folder / 'data'}.")

    stray = list(folder.rglob("*.tmp"))
    if stray:
        _die(f"Còn {len(stray)} file .tmp trong {folder} — bản export bị cắt giữa chừng.")
    return manifest


def _summary(folder: Path, manifest: dict) -> None:
    files = [p for p in folder.rglob("*") if p.is_file()]
    total = sum(p.stat().st_size for p in files)
    print(f"Thư mục   : {folder}")
    print(f"Dung lượng: {total / 1e6:,.1f} MB trong {len(files)} file")
    print(f"Publication: {manifest.get('n_publications')} xuất "
          f"/ {manifest.get('n_requested_publications')} được giao")
    skipped = manifest.get("n_skipped_publications") or 0
    if skipped:
        print(f"Bỏ qua    : {skipped} bài — {manifest.get('n_skipped_by_reason')}")
    for name in ("papers", "references", "elements", "hierarchy", "bibtex"):
        rows = manifest.get(f"n_rows_{name}")
        if rows is not None:
            print(f"  {name:<11} {rows:>12,} dòng  {manifest.get(f'n_shards_{name}'):>4} shard")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Đẩy hf_export/<MSSV> lên Hugging Face Hub")
    ap.add_argument("--mssv", required=True, help="MSSV, ví dụ 24120053")
    ap.add_argument("--repo", default=None,
                    help="Tên repo đầy đủ <user>/<name>; mặc định <user>/introds-arxiv-<MSSV>")
    ap.add_argument("--folder", type=Path, default=None, help="Mặc định hf_export/<MSSV>")
    ap.add_argument("--private", action="store_true",
                    help="Tạo repo riêng tư. Nhớ mở public trước khi nộp link.")
    ap.add_argument("--dry-run", action="store_true", help="Chỉ kiểm tra, không đẩy")
    args = ap.parse_args(argv)

    if not args.mssv.isdigit():
        ap.error("--mssv chỉ nhận chữ số")

    folder = (args.folder or (ROOT / "hf_export" / args.mssv)).resolve()
    manifest = _check_export(folder, args.mssv)
    _summary(folder, manifest)

    if args.dry_run:
        print("\n--dry-run: dừng ở đây, chưa đẩy gì.")
        return 0

    try:
        from huggingface_hub import HfApi
        from huggingface_hub.utils import HfHubHTTPError
    except ImportError:
        _die("Chưa cài huggingface_hub. Chạy: pip install -r src/requirements.txt")

    api = HfApi(token=os.environ.get("HF_TOKEN") or None)
    try:
        who = api.whoami()
    except Exception as exc:  # noqa: BLE001 — thiếu token hay token sai đều rơi vào đây
        _die("Chưa đăng nhập Hugging Face. Chạy `hf auth login`, hoặc đặt biến môi "
             f"trường HF_TOKEN bằng token loại write.\nChi tiết: {exc}")
    user = who["name"]
    repo_id = args.repo or f"{user}/{DEFAULT_PREFIX}-{args.mssv}"
    print(f"\nTài khoản : {user}")
    print(f"Repo      : {repo_id}")

    api.create_repo(repo_id=repo_id, repo_type="dataset",
                    private=args.private, exist_ok=True)
    print("Đang đẩy... (lần đầu chạy sẽ lâu, theo dõi thanh tiến trình bên dưới)")
    try:
        api.upload_folder(
            repo_id=repo_id,
            repo_type="dataset",
            folder_path=str(folder),
            ignore_patterns=list(IGNORE),
            # XOÁ shard cũ trên Hub. `upload_folder` chỉ THÊM và GHI ĐÈ, không bao
            # giờ xoá, nên lần đẩy sau mà số shard ít đi (đổi --shard-rows chẳng
            # hạn: 25.000 dòng ra ~200 file, 500.000 dòng ra ~10 file) thì 190 file
            # cũ vẫn nằm đó. Viewer đọc cả hai bộ -> dòng bị trùng, hoặc báo lỗi vì
            # lệch schema. Minh Thư chỉ ra 27/11 khi review PR #54.
            delete_patterns=["data/*/*.parquet"],
            commit_message=f"Dataset M1+M2 cho MSSV {args.mssv}",
        )
    except HfHubHTTPError as exc:
        _die(f"Hub từ chối: {exc}")

    if not (folder / "data" / "predictions").is_dir():
        print("\nGhi chú: bản này chưa có bảng `predictions` (Milestone 3). Thầy cho "
              "update bổ sung tới hạn nộp Poster, vẫn giữ nguyên link này.")

    url = f"https://huggingface.co/datasets/{repo_id}"
    print("\nXong. Link để nộp:")
    print(f"  {url}")
    if args.private:
        print("\n⚠️  Repo đang để RIÊNG TƯ. Vào Settings -> Change visibility -> Public "
              "trước khi nộp, nếu không thầy mở link sẽ báo 404.")
    print("\nKiểm thử tải lại (tuỳ chọn):")
    print(f'  python -c "from datasets import load_dataset; '
          f"print(load_dataset('{repo_id}', 'papers', split='train'))\"")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
