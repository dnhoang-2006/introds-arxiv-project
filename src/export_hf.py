"""Xuất các bảng M1/M2 thành Parquet phân mảnh, sẵn sàng đưa lên Hugging Face.

Ví dụ:
    python src/export_hf.py --mssv 24120053
    python src/export_hf.py --mssv 24120053 --shard-rows 25000 --overwrite

Mỗi bảng là một Hugging Face config riêng: papers, references, elements,
hierarchy và bibtex. Bản xuất hiện tại chưa có predictions.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

_SRC = Path(__file__).resolve().parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import config  # noqa: E402


TABLE_NAMES = ("papers", "references", "elements", "hierarchy", "bibtex")


class ExportError(RuntimeError):
    """Lỗi dữ liệu đầu vào hoặc cấu hình xuất Parquet."""


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExportError(f"Không đọc được JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ExportError(f"JSON gốc phải là object: {path}")
    return value


def _iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8-sig") as stream:
            for line_number, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ExportError(
                        f"{path}, dòng {line_number}: JSON hỏng ({exc.msg})"
                    ) from exc
                if not isinstance(value, dict):
                    raise ExportError(
                        f"{path}, dòng {line_number}: mỗi dòng phải là object JSON"
                    )
                yield value
    except OSError as exc:
        raise ExportError(f"Không đọc được JSONL {path}: {exc}") from exc


def _field(row: dict[str, Any], name: str, where: str) -> Any:
    if name not in row:
        raise ExportError(f"{where}: thiếu cột {name!r}")
    return row[name]


def _string(row: dict[str, Any], name: str, where: str, *, nullable: bool = False) -> str | None:
    value = _field(row, name, where)
    if value is None and nullable:
        return None
    if not isinstance(value, str):
        raise ExportError(f"{where}: {name} phải là chuỗi" + (" hoặc null" if nullable else ""))
    return value


def _string_list(
    row: dict[str, Any], name: str, where: str, *, nullable: bool = False
) -> list[str] | None:
    value = _field(row, name, where)
    if value is None and nullable:
        return None
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ExportError(f"{where}: {name} phải là list[string] cấp một" + (" hoặc null" if nullable else ""))
    return value


def _integer(row: dict[str, Any], name: str, where: str, *, nullable: bool = False) -> int | None:
    value = _field(row, name, where)
    if value is None and nullable:
        return None
    if type(value) is not int:
        raise ExportError(f"{where}: {name} phải là số nguyên" + (" hoặc null" if nullable else ""))
    return value


def _boolean(row: dict[str, Any], name: str, where: str) -> bool:
    value = _field(row, name, where)
    if type(value) is not bool:
        raise ExportError(f"{where}: {name} phải là boolean")
    return value


def _check_arxiv_id(row: dict[str, Any], expected: str, where: str) -> None:
    value = row.get("arxiv_id")
    if not isinstance(value, str) or config.strip_version(value) != expected:
        raise ExportError(
            f"{where}: arxiv_id {value!r} không khớp ID được giao {expected!r}"
        )


def _paper_row(meta: dict[str, Any], arxiv_id: str, path: Path) -> dict[str, Any]:
    _check_arxiv_id(meta, arxiv_id, str(path))
    return {
        "arxiv_id": arxiv_id,
        "title": _string(meta, "title", str(path)),
        "authors": _string_list(meta, "authors", str(path)),
        "submission_date": _string(meta, "submission_date", str(path)),
        "revised_dates": _string_list(meta, "revised_dates", str(path)),
        "venue": _string(meta, "venue", str(path), nullable=True),
    }


def _reference_row(row: dict[str, Any], arxiv_id: str, where: str) -> dict[str, Any]:
    _check_arxiv_id(row, arxiv_id, where)
    ref_arxiv_id = _string(row, "ref_arxiv_id", where, nullable=True)
    has_arxiv_id = _boolean(row, "has_arxiv_id", where)
    if has_arxiv_id != bool(ref_arxiv_id):
        raise ExportError(f"{where}: has_arxiv_id không khớp ref_arxiv_id")
    return {
        "arxiv_id": arxiv_id,
        "ref_s2_id": _string(row, "ref_s2_id", where, nullable=True),
        "ref_title": _string(row, "ref_title", where, nullable=True),
        "ref_authors": _string_list(row, "ref_authors", where),
        "ref_submission_date": _string(row, "ref_submission_date", where, nullable=True),
        "ref_arxiv_id": ref_arxiv_id,
        "has_arxiv_id": has_arxiv_id,
        "ref_venue": _string(row, "ref_venue", where, nullable=True),
        "ref_year": _integer(row, "ref_year", where, nullable=True),
    }


def _element_row(row: dict[str, Any], arxiv_id: str, where: str) -> dict[str, Any]:
    _check_arxiv_id(row, arxiv_id, where)
    return {
        "element_id": _string(row, "element_id", where),
        "arxiv_id": arxiv_id,
        "kind": _string(row, "kind", where),
        "content": _string(row, "content", where),
    }


def _hierarchy_row(row: dict[str, Any], arxiv_id: str, where: str) -> dict[str, Any]:
    _check_arxiv_id(row, arxiv_id, where)
    version = _integer(row, "version", where)
    if version < 1:
        raise ExportError(f"{where}: version phải >= 1")
    return {
        "arxiv_id": arxiv_id,
        "version": version,
        "element_id": _string(row, "element_id", where),
        "parent_id": _string(row, "parent_id", where),
    }


def _bibtex_row(row: dict[str, Any], arxiv_id: str, where: str) -> dict[str, Any]:
    _check_arxiv_id(row, arxiv_id, where)
    return {
        "arxiv_id": arxiv_id,
        "citation_key": _string(row, "citation_key", where),
        "entry_type": _string(row, "entry_type", where),
        "title": _string(row, "title", where, nullable=True),
        "authors": _string_list(row, "authors", where, nullable=True),
        "year": _integer(row, "year", where, nullable=True),
        "doi": _string(row, "doi", where, nullable=True),
        "journal": _string(row, "journal", where, nullable=True),
        "url": _string(row, "url", where, nullable=True),
    }


def _row_iterators(
    arxiv_ids: list[str], corpus_root: Path, parsed_root: Path
) -> dict[str, Iterator[dict[str, Any]]]:
    def papers() -> Iterator[dict[str, Any]]:
        for arxiv_id in arxiv_ids:
            path = corpus_root / config.pub_key(arxiv_id) / "paper_meta.json"
            yield _paper_row(_load_json(path), arxiv_id, path)

    def references() -> Iterator[dict[str, Any]]:
        for arxiv_id in arxiv_ids:
            path = corpus_root / config.pub_key(arxiv_id) / "references.json"
            document = _load_json(path)
            _check_arxiv_id(document, arxiv_id, str(path))
            status = document.get("status")
            if status not in {"ok", "not_indexed"}:
                raise ExportError(
                    f"{path}: status={status!r}; xử lý references lỗi/rate-limited trước khi xuất"
                )
            refs = document.get("references")
            if not isinstance(refs, list):
                raise ExportError(f"{path}: references phải là danh sách")
            if type(document.get("n_total")) is not int or document["n_total"] != len(refs):
                raise ExportError(f"{path}: n_total không khớp số dòng references")
            n_with_arxiv = sum(
                isinstance(row, dict) and bool(row.get("ref_arxiv_id")) for row in refs
            )
            if type(document.get("n_with_arxiv")) is not int or document["n_with_arxiv"] != n_with_arxiv:
                raise ExportError(f"{path}: n_with_arxiv không khớp references")
            for index, row in enumerate(refs, 1):
                if not isinstance(row, dict):
                    raise ExportError(f"{path}, reference {index}: phải là object")
                yield _reference_row(row, arxiv_id, f"{path}, reference {index}")

    def elements() -> Iterator[dict[str, Any]]:
        for arxiv_id in arxiv_ids:
            path = parsed_root / config.pub_key(arxiv_id) / "elements.jsonl"
            for index, row in enumerate(_iter_jsonl(path), 1):
                yield _element_row(row, arxiv_id, f"{path}, dòng {index}")

    def hierarchy() -> Iterator[dict[str, Any]]:
        for arxiv_id in arxiv_ids:
            path = parsed_root / config.pub_key(arxiv_id) / "hierarchy.jsonl"
            for index, row in enumerate(_iter_jsonl(path), 1):
                yield _hierarchy_row(row, arxiv_id, f"{path}, dòng {index}")

    def bibtex() -> Iterator[dict[str, Any]]:
        for arxiv_id in arxiv_ids:
            path = parsed_root / config.pub_key(arxiv_id) / "bibtex.jsonl"
            for index, row in enumerate(_iter_jsonl(path), 1):
                yield _bibtex_row(row, arxiv_id, f"{path}, dòng {index}")

    return {
        "papers": papers(),
        "references": references(),
        "elements": elements(),
        "hierarchy": hierarchy(),
        "bibtex": bibtex(),
    }


def _preflight(arxiv_ids: list[str], corpus_root: Path, parsed_root: Path) -> None:
    missing: list[str] = []
    for arxiv_id in arxiv_ids:
        folder = config.pub_key(arxiv_id)
        for path in (
            corpus_root / folder / "paper_meta.json",
            corpus_root / folder / "references.json",
            parsed_root / folder / "elements.jsonl",
            parsed_root / folder / "hierarchy.jsonl",
            parsed_root / folder / "bibtex.jsonl",
        ):
            if not path.is_file():
                missing.append(f"{arxiv_id}: {path}")
    if missing:
        preview = "\n".join(f"  - {item}" for item in missing[:20])
        extra = f"\n  ... và {len(missing) - 20} file khác" if len(missing) > 20 else ""
        raise ExportError(
            f"Thiếu {len(missing)} file đầu vào; chưa xuất dataset để tránh thiếu dữ liệu:\n"
            f"{preview}{extra}"
        )


def _table_schemas(pa: Any) -> dict[str, Any]:
    string = pa.string()
    string_list = pa.list_(string)
    return {
        "papers": pa.schema([
            pa.field("arxiv_id", string, nullable=False),
            pa.field("title", string, nullable=False),
            pa.field("authors", string_list, nullable=False),
            pa.field("submission_date", string, nullable=False),
            pa.field("revised_dates", string_list, nullable=False),
            pa.field("venue", string, nullable=True),
        ]),
        "references": pa.schema([
            pa.field("arxiv_id", string, nullable=False),
            pa.field("ref_s2_id", string, nullable=True),
            pa.field("ref_title", string, nullable=True),
            pa.field("ref_authors", string_list, nullable=False),
            pa.field("ref_submission_date", string, nullable=True),
            pa.field("ref_arxiv_id", string, nullable=True),
            pa.field("has_arxiv_id", pa.bool_(), nullable=False),
            pa.field("ref_venue", string, nullable=True),
            pa.field("ref_year", pa.int64(), nullable=True),
        ]),
        "elements": pa.schema([
            pa.field("element_id", string, nullable=False),
            pa.field("arxiv_id", string, nullable=False),
            pa.field("kind", string, nullable=False),
            pa.field("content", string, nullable=False),
        ]),
        "hierarchy": pa.schema([
            pa.field("arxiv_id", string, nullable=False),
            pa.field("version", pa.int64(), nullable=False),
            pa.field("element_id", string, nullable=False),
            pa.field("parent_id", string, nullable=False),
        ]),
        "bibtex": pa.schema([
            pa.field("arxiv_id", string, nullable=False),
            pa.field("citation_key", string, nullable=False),
            pa.field("entry_type", string, nullable=False),
            pa.field("title", string, nullable=True),
            pa.field("authors", string_list, nullable=True),
            pa.field("year", pa.int64(), nullable=True),
            pa.field("doi", string, nullable=True),
            pa.field("journal", string, nullable=True),
            pa.field("url", string, nullable=True),
        ]),
    }


def _write_shards(
    table_name: str,
    rows: Iterable[dict[str, Any]],
    root: Path,
    schema: Any,
    mssv: str,
    shard_rows: int,
    pa: Any,
    pq: Any,
) -> dict[str, Any]:
    table_dir = root / "data" / table_name
    table_dir.mkdir(parents=True, exist_ok=True)
    shard_paths: list[str] = []
    row_count = 0
    buffer: list[dict[str, Any]] = []

    def write_buffer(index: int) -> None:
        table = pa.Table.from_pylist(buffer, schema=schema)
        file_name = f"train-{mssv}-{index:05d}.parquet"
        path = table_dir / file_name
        pq.write_table(table, path, compression="zstd")
        shard_paths.append(path.relative_to(root).as_posix())

    for row in rows:
        buffer.append(row)
        row_count += 1
        if len(buffer) >= shard_rows:
            write_buffer(len(shard_paths))
            buffer.clear()

    if buffer or not shard_paths:
        write_buffer(len(shard_paths))

    return {"rows": row_count, "shards": shard_paths}


def _write_readme(root: Path) -> None:
    configs = "\n".join(
        f'  - config_name: {name}\n'
        f'    data_files:\n'
        f'      - split: train\n'
        f'        path: "data/{name}/*.parquet"'
        for name in TABLE_NAMES
    )
    readme = (
        "---\n"
        "configs:\n"
        f"{configs}\n"
        "---\n\n"
        "# arXiv Project Dataset\n\n"
        "This release contains the five Milestone 1 and Milestone 2 tables. "
        "Predictions will be added in a later release.\n\n"
        "Each table is a separate configuration: `papers`, `references`, "
        "`elements`, `hierarchy`, and `bibtex`. List-valued columns contain "
        "one-level lists of strings; table rows contain no nested JSON objects.\n"
    )
    (root / "README.md").write_text(readme, encoding="utf-8", newline="\n")


def _write_manifest(root: Path, mssv: str, ids: list[str], results: dict[str, dict[str, Any]]) -> None:
    metadata_dir = root / "metadata"
    metadata_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {
        "mssv": mssv,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "n_publications": len(ids),
        "predictions_included": False,
    }
    for table_name, result in results.items():
        manifest[f"n_rows_{table_name}"] = result["rows"]
        manifest[f"n_shards_{table_name}"] = len(result["shards"])
    path = metadata_dir / f"export-manifest-{mssv}.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _load_assigned_ids(ids_file: Path) -> list[str]:
    if not ids_file.is_file():
        raise ExportError(f"Không tìm thấy file ID được giao: {ids_file}")
    result: list[str] = []
    seen: set[str] = set()
    for line_number, raw in enumerate(ids_file.read_text(encoding="utf-8-sig").splitlines(), 1):
        value = raw.strip()
        if not value or value.startswith("#"):
            continue
        arxiv_id = config.strip_version(value)
        if arxiv_id not in seen:
            result.append(arxiv_id)
            seen.add(arxiv_id)
    if not result:
        raise ExportError(f"File ID rỗng: {ids_file}")
    return result


def _replace_output(stage: Path, output: Path, overwrite: bool) -> None:
    if not output.exists():
        stage.rename(output)
        return
    if not overwrite:
        raise ExportError(
            f"Thư mục xuất đã tồn tại: {output}. Dùng --overwrite để thay toàn bộ export của MSSV này."
        )
    if not output.is_dir():
        raise ExportError(f"Đường dẫn --out phải là thư mục: {output}")

    backup = output.with_name(f".{output.name}.backup-{os.getpid()}")
    if backup.exists():
        raise ExportError(f"Thư mục backup đã tồn tại, không tự xoá: {backup}")
    output.rename(backup)
    try:
        stage.rename(output)
    except OSError:
        backup.rename(output)
        raise
    shutil.rmtree(backup)


def export_dataset(
    mssv: str,
    arxiv_ids: list[str],
    corpus_root: Path,
    parsed_root: Path,
    output: Path,
    shard_rows: int,
    overwrite: bool = False,
) -> dict[str, dict[str, Any]]:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise ExportError(
            "Chưa cài pyarrow. Chạy pip install -r src/requirements.txt rồi thử lại."
        ) from exc

    if shard_rows < 1:
        raise ExportError("--shard-rows phải là số nguyên dương")
    output = output.resolve()
    if output.exists() and not overwrite:
        raise ExportError(
            f"Thư mục xuất đã tồn tại: {output}. Dùng --overwrite để thay toàn bộ export của MSSV này."
        )
    _preflight(arxiv_ids, corpus_root, parsed_root)

    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{output.name}.staging-", dir=output.parent))
    try:
        schemas = _table_schemas(pa)
        iterators = _row_iterators(arxiv_ids, corpus_root, parsed_root)
        results: dict[str, dict[str, Any]] = {}
        for table_name in TABLE_NAMES:
            results[table_name] = _write_shards(
                table_name=table_name,
                rows=iterators[table_name],
                root=stage,
                schema=schemas[table_name],
                mssv=mssv,
                shard_rows=shard_rows,
                pa=pa,
                pq=pq,
            )

        _write_readme(stage)
        _write_manifest(stage, mssv, arxiv_ids, results)
        _replace_output(stage, output, overwrite)
        return results
    finally:
        if stage.exists():
            shutil.rmtree(stage, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Xuất các bảng M1/M2 thành Parquet cho Hugging Face"
    )
    parser.add_argument("--mssv", required=True, help="MSSV, ví dụ 24120053; dùng ids/<MSSV>.txt")
    parser.add_argument("--ids-file", type=Path, default=None, help="Ghi đè file ids/<MSSV>.txt")
    parser.add_argument("--corpus", type=Path, default=config.CORPUS_ROOT)
    parser.add_argument(
        "--parsed",
        type=Path,
        default=Path(os.environ.get("PARSED_ROOT", config.PROJECT_ROOT / "parsed")),
    )
    parser.add_argument("--out", type=Path, default=None, help="Thư mục output; mặc định hf_export/<MSSV>")
    parser.add_argument("--shard-rows", type=int, default=25000, help="Số dòng tối đa mỗi file Parquet")
    parser.add_argument("--overwrite", action="store_true", help="Thay export cũ của MSSV này")
    args = parser.parse_args(argv)

    if not args.mssv.isdigit():
        parser.error("--mssv chỉ nhận chữ số")
    ids_file = args.ids_file or (config.IDS_ROOT / f"{args.mssv}.txt")
    output = args.out or (config.PROJECT_ROOT / "hf_export" / args.mssv)

    try:
        arxiv_ids = _load_assigned_ids(ids_file)
        results = export_dataset(
            mssv=args.mssv,
            arxiv_ids=arxiv_ids,
            corpus_root=args.corpus,
            parsed_root=args.parsed,
            output=output,
            shard_rows=args.shard_rows,
            overwrite=args.overwrite,
        )
    except ExportError as exc:
        print(f"LỖI: {exc}", file=sys.stderr)
        return 1

    print(f"Hugging Face export cho MSSV {args.mssv}: {output.resolve()}")
    print(f"Publication: {len(arxiv_ids)}")
    for table_name in TABLE_NAMES:
        result = results[table_name]
        print(f"{table_name:<12} {result['rows']:>10,} dòng  {len(result['shards']):>4} shard")
    print("predictions : chưa xuất ở bản này")
    print("Ghi chú: lệnh này chỉ tạo file Parquet cục bộ; chưa upload lên Hugging Face Hub.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
