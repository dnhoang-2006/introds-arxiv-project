"""
cross_validate.py — A3: so 3 nguồn metadata arXiv trên cùng tập ID.

    API     corpus/<pub_key>/paper_meta.json   (discovery.py)
    OAI     data/oai_records.jsonl             (oai_harvester.py)
    Kaggle  data/kaggle_records.jsonl          (kaggle_loader.py)

Chạy:
    python src/cross_validate.py --ids ids/24120053.txt --oai-sample 500
    python src/cross_validate.py --ids ids/24120053.txt --oai-sample 500 --recheck-api

Kết quả trong reports/:
    a3_coverage.csv          mỗi nguồn có / thiếu bao nhiêu ID
    a3_field_agreement.csv   mỗi cặp nguồn, mỗi trường: khớp / lệch bao nhiêu bài
    a3_three_way.csv         trên tập ID cả 3 nguồn cùng có: bao nhiêu bài khớp cả 3
    a3_versions.csv          nguồn nào cho biết số version và ngày từng version
    a3_disagreements.csv     từng trường hợp lệch, kèm 2 giá trị
    a3_author_causes.csv     nguyên nhân lệch tác giả, theo cặp nguồn
    a3_api_recheck.csv       (--recheck-api) gọi lại API cho các bài API lệch version/venue:
                             API đã khớp nguồn kia thì chỉ là lệch thời điểm, không phải lệch thật
    a3_cross_validation.md   gộp các bảng trên, để đưa vào Jupyter Book
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from itertools import combinations
from pathlib import Path
from typing import Any, Callable

import pandas as pd

import config
import kaggle_loader
import oai_harvester
import discovery
from discovery import load_ids

SOURCES = ("API", "OAI", "Kaggle")
FIELDS = ("title", "authors", "venue", "submission_date", "latest_date", "n_versions")

# Kết quả so sánh một trường giữa 2 nguồn
IDENTICAL = "identical"          # khớp nguyên văn (sau khi gộp khoảng trắng)
NORMALIZED = "normalized_equal"  # chỉ khớp sau khi bỏ LaTeX, dấu, hoa/thường, dấu câu
DIFFERENT = "different"
ONLY_LEFT = "only_left"          # chỉ nguồn bên trái có giá trị
ONLY_RIGHT = "only_right"
BOTH_NULL = "both_null"

OUTCOMES = (IDENTICAL, NORMALIZED, DIFFERENT, ONLY_LEFT, ONLY_RIGHT, BOTH_NULL)


# ----------------------------------------------------------------------
# Chuẩn hóa
# ----------------------------------------------------------------------
LATEX_ACCENTS = {
    "`": "\u0300", "'": "\u0301", "^": "\u0302", "~": "\u0303", "=": "\u0304",
    "u": "\u0306", ".": "\u0307", '"': "\u0308", "r": "\u030a", "H": "\u030b",
    "v": "\u030c", "d": "\u0323", "c": "\u0327", "k": "\u0328", "b": "\u0331",
}
LATEX_LETTERS = {
    "ss": "ß", "o": "ø", "O": "Ø", "ae": "æ", "AE": "Æ", "oe": "œ", "OE": "Œ",
    "aa": "å", "AA": "Å", "l": "ł", "L": "Ł", "i": "ı", "j": "ȷ", "DJ": "Đ", "dj": "đ",
    "deg": "°",
    # Title trên OAI/Kaggle giữ macro Hy Lạp, API đã đổi sang Unicode
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε", "varepsilon": "ε",
    "zeta": "ζ", "eta": "η", "theta": "θ", "vartheta": "θ", "iota": "ι", "kappa": "κ",
    "lambda": "λ", "mu": "μ", "nu": "ν", "xi": "ξ", "pi": "π", "rho": "ρ", "sigma": "σ",
    "tau": "τ", "upsilon": "υ", "phi": "φ", "varphi": "φ", "chi": "χ", "psi": "ψ",
    "omega": "ω", "Gamma": "Γ", "Delta": "Δ", "Theta": "Θ", "Lambda": "Λ", "Xi": "Ξ",
    "Pi": "Π", "Sigma": "Σ", "Upsilon": "Υ", "Phi": "Φ", "Psi": "Ψ", "Omega": "Ω",
}
# Khoảng trắng SAU chữ cái chỉ thuộc về mã LaTeX khi nằm trong ngoặc: \'{e }. Viết `\^o Hai`
# thì khoảng trắng đó ngăn cách 2 từ, phải giữ lại.
_ACCENT_RE = re.compile(
    r"""\\([`'^~=."]|[uvHrdckb](?![a-zA-Z]))\s*"""
    r"""(?:\{\s*(?:\\([ij])(?![a-zA-Z])|([a-zA-Z]))\s*\}|\\([ij])(?![a-zA-Z])|([a-zA-Z]))"""
)
_LETTER_RE = re.compile(r"\\([a-zA-Z]+)")
_NAME_SUFFIX_RE = re.compile(r"^(jr|sr|ii|iii|iv)\.?$", re.IGNORECASE)
_TRAILING_SUFFIX_RE = re.compile(r"[\s,]+(jr\.?|sr\.?|ii|iii|iv|v)$", re.IGNORECASE)


def clean_spaces(text: str) -> str:
    return " ".join(text.split())


def delatex(text: str) -> str:
    r"""Đổi mã LaTeX trong tên và title thành Unicode.

    >>> delatex(r"S\'ebastien Pecqueur")
    'Sébastien Pecqueur'
    >>> delatex(r"M{\"u}ller and Erd\H{o}s and \v{C}ech and G\"odel")
    'Müller and Erdős and Čech and Gödel'
    >>> delatex(r"{\O}rsted and Stra{\ss}e and \'{\i}cono")
    'Ørsted and Straße and ícono'
    >>> delatex(r"Phùng H\^o Hai and M. Rakovi\'c and Y. Kersal\'e")
    'Phùng Hô Hai and M. Raković and Y. Kersalé'
    >>> delatex(r"$\Omega^{-}$ and {\gamma}{\gamma} at 360{\deg} \to x")
    '$Ω^-$ and γγ at 360° \\to x'
    """
    def accent(match: re.Match) -> str:
        letter = next(g for g in match.groups()[1:] if g)
        return unicodedata.normalize("NFC", letter + LATEX_ACCENTS[match.group(1)])

    def letter(match: re.Match) -> str:
        return LATEX_LETTERS.get(match.group(1), match.group(0))

    text = _ACCENT_RE.sub(accent, text)
    text = _LETTER_RE.sub(letter, text)
    text = text.replace("\\&", "&").replace("~", " ")
    return clean_spaces(text.replace("{", "").replace("}", ""))


def fold(text: str) -> str:
    """Khóa so sánh: bỏ dấu, hoa/thường, khoảng trắng và dấu câu.

    >>> fold("Jung-Hoon Müller, Jr.")
    'junghoonmullerjr'
    """
    decomposed = unicodedata.normalize("NFKD", delatex(text))
    return "".join(c for c in decomposed if c.isalnum()).casefold()


def _strip_parentheses(text: str) -> str:
    """Bỏ phần trong ngoặc đơn (thường là đơn vị công tác), kể cả ngoặc lồng."""
    depth = 0
    kept: list[str] = []
    for char in text:
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        elif depth == 0:
            kept.append(char)
    return "".join(kept)


def split_authors(raw: str | None) -> list[str]:
    """Tách chuỗi tác giả của OAI/Kaggle thành danh sách tên.

    >>> split_authors(r"Jung-Hoon Jung and S\\'ebastien Pecqueur")
    ['Jung-Hoon Jung', 'Sébastien Pecqueur']
    >>> split_authors("A. Bal (MIT), B. Cole, Jr., C. Dee (1,2) and D. Eve")
    ['A. Bal', 'B. Cole, Jr.', 'C. Dee', 'D. Eve']
    """
    if not raw:
        return []
    text = delatex(_strip_parentheses(raw))
    parts = [p.strip() for p in re.split(r",|;|:|\band\b|&", text) if p.strip()]
    names: list[str] = []
    for part in parts:
        if names and _NAME_SUFFIX_RE.match(part):
            names[-1] = f"{names[-1]}, {part}"
        else:
            names.append(part)
    return names


def to_utc(value: str | None) -> str | None:
    """ISO 8601 của API hoặc RFC 2822 của OAI/Kaggle -> ISO 8601 UTC đến giây."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        parsed = parsedate_to_datetime(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")


# ----------------------------------------------------------------------
# Đưa 3 nguồn về cùng một dạng
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class Canonical:
    """Một bài theo một nguồn. Thiếu thì None."""

    title: str | None
    authors: tuple[str, ...]
    authors_raw: str | None
    venue: str | None
    submission_date: str | None
    latest_date: str | None
    n_versions: int | None
    all_version_dates: bool  # nguồn có cho biết ngày của MỌI version không


def from_api(meta: dict) -> Canonical:
    revised = meta.get("revised_dates") or []
    submission = to_utc(meta.get("submission_date"))
    authors = tuple(meta.get("authors") or [])
    return Canonical(
        title=clean_spaces(meta["title"]) if meta.get("title") else None,
        authors=authors,
        authors_raw=None,
        venue=clean_spaces(meta["venue"]) if meta.get("venue") else None,
        submission_date=submission,
        latest_date=to_utc(revised[-1]) if revised else submission,
        n_versions=meta.get("n_versions"),
        all_version_dates=bool(meta.get("revised_dates_complete")),
    )


def _from_raw(title: str | None, authors: str | None, venue: str | None,
              version_dates: list[str | None]) -> Canonical:
    dates = [to_utc(d) for d in version_dates]
    return Canonical(
        title=clean_spaces(title) if title else None,
        authors=tuple(split_authors(authors)),
        authors_raw=clean_spaces(authors) if authors else None,
        venue=clean_spaces(venue) if venue else None,
        submission_date=dates[0] if dates else None,
        latest_date=dates[-1] if dates else None,
        n_versions=len(dates) or None,
        all_version_dates=bool(dates) and all(dates),
    )


def from_oai(record: dict) -> Canonical:
    return _from_raw(record.get("title"), record.get("authors"), record.get("journal_ref"),
                     [v.get("date") for v in record.get("versions") or []])


def from_kaggle(record: dict) -> Canonical:
    return _from_raw(record.get("title"), record.get("authors"), record.get("journal-ref"),
                     [v.get("created") for v in record.get("versions") or []])


def load_api(ids: list[str]) -> dict[str, dict]:
    metas: dict[str, dict] = {}
    for arxiv_id in ids:
        path = config.pub_dir(arxiv_id) / "paper_meta.json"
        if path.exists():
            metas[arxiv_id] = json.loads(path.read_text(encoding="utf-8"))
    return metas


# ----------------------------------------------------------------------
# So sánh
# ----------------------------------------------------------------------
def _compare_values(left: Any, right: Any, key: Callable[[Any], Any] | None = None) -> str:
    left_empty, right_empty = left in (None, (), ""), right in (None, (), "")
    if left_empty and right_empty:
        return BOTH_NULL
    if right_empty:
        return ONLY_LEFT
    if left_empty:
        return ONLY_RIGHT
    if left == right:
        return IDENTICAL
    if key is not None and key(left) == key(right):
        return NORMALIZED
    return DIFFERENT


def _author_key(names: tuple[str, ...]) -> tuple[str, ...]:
    # API có lúc coi dấu ":" là một tác giả riêng; fold ra rỗng thì bỏ
    return tuple(key for key in map(fold, names) if key)


def author_gap_cause(left: tuple[str, ...], right: tuple[str, ...]) -> str:
    """Vì sao 2 danh sách tác giả lệch. `left` là nguồn có khả năng tách tên sai (API).

    >>> author_gap_cause(("Timothy Chase",), ("Timothy Chase Jr",))
    'suffix_dropped'
    >>> author_gap_cause((" Chun-Fu", " Chen"), ("Chun-Fu Chen",))
    'name_split_at_parenthesis'
    >>> author_gap_cause(("A Bee", "C Dee", "E Eff"), ("A Bee C Dee E Eff",))
    'raw_without_separator'
    >>> author_gap_cause(("A Bee",), ("Z Zed",))
    'other'
    """
    left_keys = _author_key(left)
    right_keys = _author_key(tuple(_TRAILING_SUFFIX_RE.sub("", name) for name in right))
    if len(right) == 1 and len(left_keys) > 2 and "".join(left_keys) == right_keys[0]:
        return "raw_without_separator"
    if left_keys == right_keys:
        return "suffix_dropped"
    if "".join(left_keys) == "".join(right_keys):
        return "name_split_at_parenthesis"
    return "other"


def compare_field(field: str, left: Canonical, right: Canonical) -> str:
    if field == "authors":
        # Cả 2 có chuỗi gốc (OAI, Kaggle) thì so chuỗi gốc trước
        if left.authors_raw and left.authors_raw == right.authors_raw:
            return IDENTICAL
        return _compare_values(left.authors, right.authors, _author_key)
    if field in ("title", "venue"):
        return _compare_values(getattr(left, field), getattr(right, field), fold)
    return _compare_values(getattr(left, field), getattr(right, field))


def _display(value: Any) -> str:
    if isinstance(value, tuple):
        return "; ".join(value)
    return "" if value is None else str(value)


def compare_sources(tables: dict[str, dict[str, Canonical]]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """So từng cặp nguồn trên các ID cả 2 cùng có. Trả (bảng tổng hợp, từng ca lệch)."""
    summary: list[dict[str, Any]] = []
    disagreements: list[dict[str, Any]] = []
    for left_name, right_name in combinations(SOURCES, 2):
        left_table, right_table = tables[left_name], tables[right_name]
        common = sorted(set(left_table) & set(right_table))
        for field in FIELDS:
            counts = dict.fromkeys(OUTCOMES, 0)
            for arxiv_id in common:
                left, right = left_table[arxiv_id], right_table[arxiv_id]
                outcome = compare_field(field, left, right)
                counts[outcome] += 1
                if outcome in (NORMALIZED, DIFFERENT, ONLY_LEFT, ONLY_RIGHT):
                    disagreements.append({
                        "arxiv_id": arxiv_id, "field": field,
                        "left_source": left_name, "right_source": right_name,
                        "outcome": outcome,
                        "left_value": _display(getattr(left, field)),
                        "right_value": _display(getattr(right, field)),
                        "cause": (author_gap_cause(left.authors, right.authors)
                                  if field == "authors" and outcome == DIFFERENT else ""),
                    })
            summary.append({"pair": f"{left_name} vs {right_name}", "field": field,
                            "n_compared": len(common), **counts})
    columns = ["arxiv_id", "field", "left_source", "right_source", "outcome",
               "left_value", "right_value", "cause"]
    return pd.DataFrame(summary), pd.DataFrame(disagreements, columns=columns)


def three_way(tables: dict[str, dict[str, Canonical]]) -> pd.DataFrame:
    """Trên các ID cả 3 nguồn cùng có: bao nhiêu bài khớp ở cả 3 cặp."""
    common = sorted(set.intersection(*(set(tables[s]) for s in SOURCES)))
    rows = []
    for field in FIELDS:
        strict = loose = 0
        for arxiv_id in common:
            outcomes = [compare_field(field, tables[a][arxiv_id], tables[b][arxiv_id])
                        for a, b in combinations(SOURCES, 2)]
            strict += all(o in (IDENTICAL, BOTH_NULL) for o in outcomes)
            loose += all(o in (IDENTICAL, NORMALIZED, BOTH_NULL) for o in outcomes)
        rows.append({
            "field": field, "n_common": len(common),
            "all_three_identical": strict,
            "all_three_after_normalize": loose,
            "any_disagreement": len(common) - loose,
        })
    return pd.DataFrame(rows)


def coverage(ids: list[str], tables: dict[str, dict[str, Canonical]]) -> pd.DataFrame:
    wanted = set(ids)
    rows = []
    for source in SOURCES:
        have = wanted & set(tables[source])
        rows.append({"source": source, "n_assigned": len(wanted), "n_present": len(have),
                     "n_missing": len(wanted) - len(have)})
    return pd.DataFrame(rows)


def version_report(tables: dict[str, dict[str, Canonical]]) -> pd.DataFrame:
    """Nguồn nào cho biết số version, và có đủ ngày từng version không."""
    how = {
        "API": "Suy từ hậu tố vN của entry_id; chỉ có ngày v1 và ngày bản mới nhất",
        "OAI": "Liệt kê từng <version> trong arXivRaw: ngày và dung lượng",
        "Kaggle": "Liệt kê từng phần tử versions: ngày, không có dung lượng",
    }
    rows = []
    for source in SOURCES:
        table = tables[source].values()
        multi = [c for c in table if (c.n_versions or 0) >= 3]
        rows.append({
            "source": source, "how_version_count_is_known": how[source],
            "n_papers": len(table),
            "n_with_version_count": sum(c.n_versions is not None for c in table),
            "n_with_3plus_versions": len(multi),
            "n_3plus_with_all_version_dates": sum(c.all_version_dates for c in multi),
        })
    return pd.DataFrame(rows)


def recheck_api(disagreements: pd.DataFrame) -> pd.DataFrame:
    """Gọi lại API cho các ca API lệch version/venue với nguồn khác.

    paper_meta.json là ảnh chụp lúc chạy discovery, nên bài có version mới sau đó sẽ lệch.
    Trả mỗi ca một dòng, `verdict` cho biết đó là lệch thời điểm hay lệch thật.
    """
    cases = disagreements[
        (disagreements["left_source"] == "API")
        & (disagreements["field"].isin(["n_versions", "venue"]))
        & (disagreements["outcome"] != NORMALIZED)
    ]
    columns = ["arxiv_id", "field", "other_source", "api_at_discovery", "api_now",
               "other_value", "verdict"]
    if cases.empty:
        return pd.DataFrame(columns=columns)

    ids = sorted(set(cases["arxiv_id"]))
    client = discovery.build_client()
    fresh: dict[str, discovery.PaperMeta] = {}
    for start in range(0, len(ids), discovery.BATCH_SIZE):
        fresh.update(discovery.resolve_batch(ids[start:start + discovery.BATCH_SIZE], client))

    rows = []
    for case in cases.itertuples(index=False):
        meta = fresh.get(case.arxiv_id)
        now = "" if meta is None else str(
            meta.n_versions if case.field == "n_versions" else meta.venue or "")
        rows.append({
            "arxiv_id": case.arxiv_id, "field": case.field, "other_source": case.right_source,
            "api_at_discovery": case.left_value, "api_now": now, "other_value": case.right_value,
            "verdict": "stale_snapshot" if now == case.right_value else "still_differs",
        })
    return pd.DataFrame(rows, columns=columns)


# ----------------------------------------------------------------------
# Xuất báo cáo
# ----------------------------------------------------------------------
def _markdown_table(frame: pd.DataFrame) -> str:
    header = "| " + " | ".join(str(c) for c in frame.columns) + " |"
    rule = "|" + "---|" * len(frame.columns)
    rows = ["| " + " | ".join(str(v) for v in row) + " |" for row in frame.itertuples(index=False)]
    return "\n".join([header, rule, *rows])


def write_reports(out_dir: Path, ids: list[str], tables: dict[str, dict[str, Canonical]],
                  provenance: dict[str, str]) -> dict[str, pd.DataFrame]:
    out_dir.mkdir(parents=True, exist_ok=True)
    agreement, disagreements = compare_sources(tables)
    frames = {
        "coverage": coverage(ids, tables),
        "three_way": three_way(tables),
        "field_agreement": agreement,
        "versions": version_report(tables),
    }
    for name, frame in frames.items():
        frame.to_csv(out_dir / f"a3_{name}.csv", index=False, encoding="utf-8")
    disagreements.to_csv(out_dir / "a3_disagreements.csv", index=False, encoding="utf-8")
    authors = disagreements[disagreements["cause"] != ""]
    frames["author_causes"] = (
        authors.assign(pair=authors["left_source"] + " vs " + authors["right_source"])
        .groupby(["pair", "cause"]).size().reset_index(name="n_papers")
    )
    frames["author_causes"].to_csv(out_dir / "a3_author_causes.csv", index=False, encoding="utf-8")

    sections = [
        "# So sánh 3 nguồn metadata arXiv",
        "\n".join(f"- **{k}**: {v}" for k, v in provenance.items()),
        "## Độ phủ\n\n" + _markdown_table(frames["coverage"]),
        "## Khớp cả 3 nguồn trên tập ID chung\n\n" + _markdown_table(frames["three_way"]),
        "## Khớp theo từng cặp nguồn\n\n" + _markdown_table(frames["field_agreement"]),
        "## Nguyên nhân lệch tác giả\n\n" + _markdown_table(frames["author_causes"]),
        "## Số version\n\n" + _markdown_table(frames["versions"]),
    ]
    (out_dir / "a3_cross_validation.md").write_text("\n\n".join(sections) + "\n", encoding="utf-8")
    return {**frames, "disagreements": disagreements}


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="So 3 nguồn metadata arXiv trên cùng tập ID")
    parser.add_argument("--ids", required=True, help="File ID (1 ID/dòng) hoặc danh sách ngăn bởi dấu phẩy")
    parser.add_argument("--oai", type=Path, default=oai_harvester.RECORDS_PATH)
    parser.add_argument("--kaggle", type=Path, default=kaggle_loader.DEFAULT_OUTPUT)
    parser.add_argument("--out", type=Path, default=config.REPORTS_ROOT)
    parser.add_argument("--oai-sample", type=int, default=None,
                        help="Chỉ so OAI trên mẫu N ID đã lấy bằng `oai_harvester.py get --sample N`")
    parser.add_argument("--seed", type=int, default=42, help="Seed của mẫu, khớp với lệnh get")
    parser.add_argument("--recheck-api", action="store_true",
                        help="Gọi lại API để tách lệch thời điểm khỏi lệch thật")
    args = parser.parse_args()

    ids = list(dict.fromkeys(config.strip_version(i) for i in load_ids(args.ids)))
    if not ids:
        sys.exit("Không đọc được ID nào.")
    if not args.kaggle.exists():
        sys.exit(f"Thiếu {args.kaggle}. Chạy kaggle_loader.py trước.")

    wanted = set(ids)
    # Record lấy từ ListRecords lệch về bài vừa bị sửa trong cửa sổ ngày, nên tỉ lệ khớp
    # chỉ có nghĩa trên mẫu ngẫu nhiên
    oai_wanted = set(oai_harvester.choose_sample(ids, args.oai_sample, args.seed))
    oai_raw = oai_harvester.load_records(args.oai)
    kaggle_raw = kaggle_loader.load_records(args.kaggle)
    tables = {
        "API": {i: from_api(m) for i, m in load_api(ids).items()},
        "OAI": {i: from_oai(r) for i, r in oai_raw.items() if i in oai_wanted and not r.get("deleted")},
        "Kaggle": {i: from_kaggle(r) for i, r in kaggle_raw.items() if i in wanted},
    }

    api_times = [m["discovered_at"] for m in load_api(ids).values() if m.get("discovered_at")]
    oai_times = [r["harvested_at"] for i, r in oai_raw.items() if i in oai_wanted]
    kaggle_log = config.LOGS_ROOT / "kaggle_loader.json"
    snapshot = (json.loads(kaggle_log.read_text(encoding="utf-8")).get("snapshot_date")
                if kaggle_log.exists() else "không rõ")
    provenance = {
        "API": f"paper_meta.json, lấy từ {min(api_times, default='?')[:10]} "
               f"đến {max(api_times, default='?')[:10]}",
        "OAI": f"định dạng arXivRaw, lấy từ {min(oai_times, default='?')[:10]} "
               f"đến {max(oai_times, default='?')[:10]}",
        "Kaggle": f"Cornell snapshot ngày {snapshot}",
    }

    frames = write_reports(args.out, ids, tables, provenance)
    if args.recheck_api:
        recheck = recheck_api(frames["disagreements"])
        recheck.to_csv(args.out / "a3_api_recheck.csv", index=False, encoding="utf-8")
        print(recheck.groupby(["field", "other_source", "verdict"]).size().to_string(), "\n")
    print(frames["coverage"].to_string(index=False), "\n")
    print(frames["three_way"].to_string(index=False), "\n")
    print(frames["field_agreement"].to_string(index=False), "\n")
    print(frames["versions"].drop(columns="how_version_count_is_known").to_string(index=False), "\n")
    print(f"Số ca lệch: {len(frames['disagreements'])}")
    print(f"Báo cáo: {args.out / 'a3_cross_validation.md'}")


if __name__ == "__main__":
    main()
