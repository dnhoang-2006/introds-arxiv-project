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
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
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
    except UnicodeDecodeError as exc:
        raise ExportError(f"{path}: không phải UTF-8 hợp lệ ({exc.reason})") from exc
    except OSError as exc:
        raise ExportError(f"Không đọc được JSONL {path}: {exc}") from exc


def _field(row: dict[str, Any], name: str, where: str) -> Any:
    if name not in row:
        raise ExportError(f"{where}: thiếu cột {name!r}")
    return row[name]


def _check_utf8(value: str, name: str, where: str) -> None:
    """JSON cho phép escape surrogate lẻ (\\ud835) nhưng Parquet thì không: pyarrow
    sẽ ném UnicodeEncodeError lúc ghi shard, làm văng cả lần xuất. Bắt sớm ở đây để
    chỉ bỏ qua bài chứa chuỗi đó."""
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ExportError(f"{where}: {name} chứa ký tự không mã hoá được UTF-8 ({exc.reason})") from exc


def _string(row: dict[str, Any], name: str, where: str, *, nullable: bool = False) -> str | None:
    value = _field(row, name, where)
    if value is None and nullable:
        return None
    if not isinstance(value, str):
        raise ExportError(f"{where}: {name} phải là chuỗi" + (" hoặc null" if nullable else ""))
    _check_utf8(value, name, where)
    return value


def _string_list(
    row: dict[str, Any], name: str, where: str, *, nullable: bool = False
) -> list[str] | None:
    value = _field(row, name, where)
    if value is None and nullable:
        return None
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ExportError(f"{where}: {name} phải là list[string] cấp một" + (" hoặc null" if nullable else ""))
    for item in value:
        _check_utf8(item, name, where)
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


def _reference_row(row: dict[str, Any], arxiv_id: str, where: str) -> dict[str, Any] | None:
    """Một dòng bảng `references`, hoặc None nếu reference này không có arXiv ID.

    Đề M1: *"only the references carrying an arXiv ID become rows of the published
    references table"*, `ref_arxiv_id` non-null, đúng 6 cột theo thứ tự của đề.
    references.json vẫn giữ mọi reference (docs/schema.md mục 4); việc lọc chỉ xảy
    ra ở đây. Các trường khác vẫn được validate để file hỏng không lọt qua im lặng.
    """
    _check_arxiv_id(row, arxiv_id, where)
    ref_arxiv_id = _string(row, "ref_arxiv_id", where, nullable=True)
    has_arxiv_id = _boolean(row, "has_arxiv_id", where)
    if has_arxiv_id != bool(ref_arxiv_id):
        raise ExportError(f"{where}: has_arxiv_id không khớp ref_arxiv_id")
    out = {
        "arxiv_id": arxiv_id,
        "ref_arxiv_id": ref_arxiv_id,
        "ref_title": _string(row, "ref_title", where, nullable=True),
        "ref_authors": _string_list(row, "ref_authors", where),
        "ref_submission_date": _string(row, "ref_submission_date", where, nullable=True),
        "ref_s2_id": _string(row, "ref_s2_id", where, nullable=True),
    }
    return out if ref_arxiv_id else None


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


def _publication_rows(
    arxiv_id: str, corpus_root: Path, parsed_root: Path
) -> dict[str, list[dict[str, Any]]]:
    """Đọc và validate toàn bộ dòng của MỘT publication cho cả năm bảng.

    Gom theo bài (không theo bảng) để một bài có nội dung hỏng — JSON lỗi,
    n_total lệch, cột sai kiểu — bị loại khỏi cả năm bảng cùng lúc thay vì làm
    văng cả lần xuất giữa chừng. Ném ExportError nếu bài này không xuất được.
    """
    folder = config.pub_key(arxiv_id)
    corpus_dir = corpus_root / folder
    parsed_dir = parsed_root / folder

    meta_path = corpus_dir / "paper_meta.json"
    papers = [_paper_row(_load_json(meta_path), arxiv_id, meta_path)]

    refs_path = corpus_dir / "references.json"
    document = _load_json(refs_path)
    _check_arxiv_id(document, arxiv_id, str(refs_path))
    status = document.get("status")
    if status not in {"ok", "not_indexed"}:
        raise ExportError(
            f"{refs_path}: status={status!r}; xử lý references lỗi/rate-limited trước khi xuất"
        )
    refs = document.get("references")
    if not isinstance(refs, list):
        raise ExportError(f"{refs_path}: references phải là danh sách")
    if type(document.get("n_total")) is not int or document["n_total"] != len(refs):
        raise ExportError(f"{refs_path}: n_total không khớp số dòng references")
    n_with_arxiv = sum(
        isinstance(row, dict) and bool(row.get("ref_arxiv_id")) for row in refs
    )
    if type(document.get("n_with_arxiv")) is not int or document["n_with_arxiv"] != n_with_arxiv:
        raise ExportError(f"{refs_path}: n_with_arxiv không khớp references")
    references: list[dict[str, Any]] = []
    for index, row in enumerate(refs, 1):
        if not isinstance(row, dict):
            raise ExportError(f"{refs_path}, reference {index}: phải là object")
        ref_row = _reference_row(row, arxiv_id, f"{refs_path}, reference {index}")
        if ref_row is not None:
            references.append(ref_row)

    def jsonl_rows(name: str, build: Any) -> list[dict[str, Any]]:
        path = parsed_dir / name
        return [
            build(row, arxiv_id, f"{path}, dòng {index}")
            for index, row in enumerate(_iter_jsonl(path), 1)
        ]

    return {
        "papers": papers,
        "references": references,
        "elements": jsonl_rows("elements.jsonl", _element_row),
        "hierarchy": jsonl_rows("hierarchy.jsonl", _hierarchy_row),
        "bibtex": jsonl_rows("bibtex.jsonl", _bibtex_row),
    }


#: Lý do một publication bị loại khỏi CẢ NĂM bảng, ghi vào manifest.
SKIP_MISSING_PARSED_DIR = "missing_parsed_directory"
SKIP_MISSING_INPUT_FILE = "missing_input_file"
SKIP_UNREADABLE_REFERENCES = "unreadable_references"
SKIP_BAD_REFERENCES_STATUS = "bad_references_status"
#: File đủ và đọc được nhưng nội dung sai schema/không nhất quán (JSONL hỏng một
#: dòng, n_total lệch, cột sai kiểu...). Phát hiện lúc đọc từng bài để xuất.
SKIP_INVALID_CONTENT = "invalid_content"


def _skip_reason(
    arxiv_id: str, corpus_root: Path, parsed_root: Path
) -> tuple[str, str] | None:
    """(lý do, chi tiết) nếu publication này không xuất được, None nếu xuất được.

    Một publication thiếu bất kỳ đầu vào nào đều bị loại khỏi **cả năm bảng**, không
    phải chỉ bảng thiếu. Nếu chỉ loại khỏi một bảng thì `papers` sẽ có bài mà
    `references` không có dòng nào — người đọc dataset hiểu nhầm là bài đó không có
    reference, trong khi thật ra là chưa crawl được.
    """
    folder = config.pub_key(arxiv_id)
    parsed_dir = parsed_root / folder
    if not parsed_dir.is_dir():
        return (SKIP_MISSING_PARSED_DIR, str(parsed_dir))

    refs_path = corpus_root / folder / "references.json"
    for path in (
        corpus_root / folder / "paper_meta.json",
        refs_path,
        parsed_dir / "elements.jsonl",
        parsed_dir / "hierarchy.jsonl",
        parsed_dir / "bibtex.jsonl",
    ):
        if not path.is_file():
            return (SKIP_MISSING_INPUT_FILE, str(path))

    try:
        status = _load_json(refs_path).get("status")
    except ExportError as exc:
        return (SKIP_UNREADABLE_REFERENCES, str(exc))
    if status not in {"ok", "not_indexed"}:
        # rate_limited / error: reference của bài này là CHƯA BIẾT chứ không phải
        # rỗng, nên xuất ra sẽ là nói dối. Nhờ người crawl bù rồi xuất lại.
        return (SKIP_BAD_REFERENCES_STATUS, f"status={status!r}")
    return None


def _partition_ids(
    arxiv_ids: list[str],
    corpus_root: Path,
    parsed_root: Path,
    *,
    strict: bool = False,
) -> tuple[list[str], list[dict[str, str]]]:
    """Tách ID xuất được khỏi ID phải bỏ qua, kèm lý do từng bài.

    Mặc định **bỏ qua và ghi vào manifest** thay vì dừng cả lần xuất: 1 bài hỏng
    trong 5.000 không nên chặn cả nhóm nộp link. `--strict` khôi phục hành vi dừng.
    """
    export_ids: list[str] = []
    skipped: list[dict[str, str]] = []
    for arxiv_id in arxiv_ids:
        reason = _skip_reason(arxiv_id, corpus_root, parsed_root)
        if reason is None:
            export_ids.append(arxiv_id)
        else:
            skipped.append({"arxiv_id": arxiv_id, "reason": reason[0], "detail": reason[1]})

    if strict and skipped:
        preview = "\n".join(
            f"  - {s['arxiv_id']}: {s['reason']} ({s['detail']})" for s in skipped[:20]
        )
        extra = f"\n  ... và {len(skipped) - 20} bài khác" if len(skipped) > 20 else ""
        raise ExportError(
            f"--strict: {len(skipped)}/{len(arxiv_ids)} bài thiếu đầu vào, chưa xuất:\n"
            f"{preview}{extra}"
        )
    if not export_ids:
        raise ExportError(
            f"Không bài nào trong {len(arxiv_ids)} ID được giao có đủ đầu vào trong "
            f"{parsed_root} và {corpus_root}; không tạo dataset rỗng."
        )
    return export_ids, skipped


def _table_schemas(pa: Any) -> dict[str, Any]:
    string = pa.string()
    string_list = pa.list_(string)
    # Đề ghi "string, dictionary" cho cột phân loại (elements.kind, bibtex.entry_type,
    # sau này predictions.partition): lưu dạng dictionary-encoded string.
    dictionary = pa.dictionary(pa.int32(), string)
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
            # Đúng 6 cột, đúng thứ tự bảng `references` trong đề M1.
            pa.field("arxiv_id", string, nullable=False),
            pa.field("ref_arxiv_id", string, nullable=False),
            pa.field("ref_title", string, nullable=True),
            pa.field("ref_authors", string_list, nullable=False),
            pa.field("ref_submission_date", string, nullable=True),
            pa.field("ref_s2_id", string, nullable=True),
        ]),
        "elements": pa.schema([
            pa.field("element_id", string, nullable=False),
            pa.field("arxiv_id", string, nullable=False),
            pa.field("kind", dictionary, nullable=False),
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
            pa.field("entry_type", dictionary, nullable=False),
            pa.field("title", string, nullable=True),
            pa.field("authors", string_list, nullable=True),
            pa.field("year", pa.int64(), nullable=True),
            pa.field("doi", string, nullable=True),
            pa.field("journal", string, nullable=True),
            pa.field("url", string, nullable=True),
        ]),
    }


class _ShardWriter:
    """Ghi một bảng thành các shard Parquet, nhận dòng dần dần theo từng bài."""

    def __init__(
        self, table_name: str, root: Path, schema: Any, mssv: str, shard_rows: int,
        pa: Any, pq: Any,
    ) -> None:
        self.table_dir = root / "data" / table_name
        self.table_dir.mkdir(parents=True, exist_ok=True)
        self.root, self.schema, self.mssv, self.shard_rows = root, schema, mssv, shard_rows
        self.pa, self.pq = pa, pq
        self.shard_paths: list[str] = []
        self.row_count = 0
        self.buffer: list[dict[str, Any]] = []

    def _flush(self) -> None:
        table = self.pa.Table.from_pylist(self.buffer, schema=self.schema)
        path = self.table_dir / f"train-{self.mssv}-{len(self.shard_paths):05d}.parquet"
        self.pq.write_table(table, path, compression="zstd")
        self.shard_paths.append(path.relative_to(self.root).as_posix())
        self.buffer.clear()

    def add(self, rows: Iterable[dict[str, Any]]) -> None:
        for row in rows:
            self.buffer.append(row)
            self.row_count += 1
            if len(self.buffer) >= self.shard_rows:
                self._flush()

    def close(self) -> dict[str, Any]:
        if self.buffer or not self.shard_paths:
            self._flush()
        return {"rows": self.row_count, "shards": self.shard_paths}


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
        "one-level lists of strings; table rows contain no nested JSON objects. "
        "`kind` and `entry_type` are dictionary-encoded strings. "
        "The `references` table keeps only crawled references that carry an arXiv "
        "ID, as the matching pool keys on arXiv identifiers. "
        "A paper missing any required input — parsed output, `paper_meta.json`, or "
        "usable `references.json` — or whose input fails validation is omitted from all five tables rather than "
        "from just one, so the tables stay consistent with each other. The export "
        "manifest lists every skipped ID with its reason; read it before treating "
        "this dataset as complete.\n"
    )
    (root / "README.md").write_text(readme, encoding="utf-8", newline="\n")


def _write_manifest(
    root: Path,
    mssv: str,
    ids: list[str],
    requested_ids: list[str],
    skipped: list[dict[str, str]],
    results: dict[str, dict[str, Any]],
) -> None:
    metadata_dir = root / "metadata"
    metadata_dir.mkdir(parents=True, exist_ok=True)
    by_reason: dict[str, int] = {}
    for item in skipped:
        by_reason[item["reason"]] = by_reason.get(item["reason"], 0) + 1
    manifest: dict[str, Any] = {
        "mssv": mssv,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "n_publications": len(ids),
        "n_requested_publications": len(requested_ids),
        "n_skipped_publications": len(skipped),
        # Mỗi bài bị bỏ qua có lý do riêng; con số gộp theo lý do để tiện trích vào
        # mục "giới hạn đã biết" của báo cáo.
        "n_skipped_by_reason": dict(sorted(by_reason.items())),
        "skipped": skipped,
        "skipped_ids": [item["arxiv_id"] for item in skipped],
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
    try:
        lines = ids_file.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise ExportError(f"Không đọc được file ID {ids_file}: {exc}") from exc
    for line_number, raw in enumerate(lines, 1):
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
    strict: bool = False,
) -> tuple[dict[str, dict[str, Any]], list[str], list[dict[str, str]]]:
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
    requested_ids = arxiv_ids
    candidate_ids, skipped = _partition_ids(
        requested_ids, corpus_root, parsed_root, strict=strict
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{output.name}.staging-", dir=output.parent))
    try:
        schemas = _table_schemas(pa)
        writers = {
            name: _ShardWriter(name, stage, schemas[name], mssv, shard_rows, pa, pq)
            for name in TABLE_NAMES
        }
        exported: list[str] = []
        for arxiv_id in candidate_ids:
            try:
                rows = _publication_rows(arxiv_id, corpus_root, parsed_root)
            except ExportError as exc:
                if strict:
                    raise ExportError(f"--strict: {arxiv_id}: {exc}") from exc
                skipped.append(
                    {"arxiv_id": arxiv_id, "reason": SKIP_INVALID_CONTENT, "detail": str(exc)}
                )
                continue
            for name in TABLE_NAMES:
                writers[name].add(rows[name])
            exported.append(arxiv_id)
        if not exported:
            raise ExportError(
                f"Không bài nào trong {len(requested_ids)} ID được giao có dữ liệu hợp lệ; "
                "không tạo dataset rỗng."
            )
        export_ids = exported
        order = {arxiv_id: i for i, arxiv_id in enumerate(requested_ids)}
        skipped.sort(key=lambda item: order[item["arxiv_id"]])
        results = {name: writers[name].close() for name in TABLE_NAMES}

        _write_readme(stage)
        _write_manifest(stage, mssv, export_ids, requested_ids, skipped, results)
        _replace_output(stage, output, overwrite)
        return results, export_ids, skipped
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
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Dừng hẳn nếu có bài thiếu đầu vào, thay vì bỏ qua và ghi vào manifest",
    )
    args = parser.parse_args(argv)

    if not args.mssv.isdigit():
        parser.error("--mssv chỉ nhận chữ số")
    ids_file = args.ids_file or (config.IDS_ROOT / f"{args.mssv}.txt")
    output = args.out or (config.PROJECT_ROOT / "hf_export" / args.mssv)

    try:
        arxiv_ids = _load_assigned_ids(ids_file)
        results, export_ids, skipped = export_dataset(
            mssv=args.mssv,
            arxiv_ids=arxiv_ids,
            corpus_root=args.corpus,
            parsed_root=args.parsed,
            output=output,
            shard_rows=args.shard_rows,
            overwrite=args.overwrite,
            strict=args.strict,
        )
    except ExportError as exc:
        print(f"LỖI: {exc}", file=sys.stderr)
        return 1

    print(f"Hugging Face export cho MSSV {args.mssv}: {output.resolve()}")
    print(f"Publication: {len(export_ids)} xuất / {len(arxiv_ids)} được giao")
    if skipped:
        by_reason: dict[str, int] = {}
        for item in skipped:
            by_reason[item["reason"]] = by_reason.get(item["reason"], 0) + 1
        print(f"Bỏ qua {len(skipped)} bài, theo lý do:")
        for reason, count in sorted(by_reason.items()):
            print(f"  {reason:<28} {count:>6}")
        for item in skipped[:10]:
            print(f"  - {item['arxiv_id']}: {item['reason']} ({item['detail']})")
        if len(skipped) > 10:
            print(f"  ... và {len(skipped) - 10} bài khác; xem metadata export manifest")
    for table_name in TABLE_NAMES:
        result = results[table_name]
        print(f"{table_name:<12} {result['rows']:>10,} dòng  {len(result['shards']):>4} shard")
    print("predictions : chưa xuất ở bản này")
    print("Ghi chú: lệnh này chỉ tạo file Parquet cục bộ; chưa upload lên Hugging Face Hub.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
    