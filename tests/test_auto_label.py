from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

SRC_DIR = str(Path(__file__).resolve().parent.parent / "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from matching.auto_label import (  # noqa: E402
    extract_arxiv_id_from_doi,
    extract_arxiv_id_from_url,
    label_entries,
    label_publication,
    load_arxiv_candidates,
    load_bibtex_entries,
    match_entry,
    write_jsonl_atomic,
)


def _make_entry(
    citation_key: str = "vaswani2017",
    *,
    arxiv_id: str = "2503.11918",
    doi: str | None = None,
    url: str | None = None,
    title: str | None = "Attention Is All You Need",
) -> dict[str, Any]:
    return {
        "arxiv_id": arxiv_id,
        "citation_key": citation_key,
        "entry_type": "article",
        "title": title,
        "authors": ["Vaswani, Ashish"],
        "year": 2017,
        "doi": doi,
        "journal": None,
        "url": url,
    }


def _make_ref(
    ref_arxiv_id: str | None,
    *,
    ref_title: str | None = "Attention Is All You Need",
    ref_doi: str | None = None,
) -> dict[str, Any]:
    ref: dict[str, Any] = {
        "arxiv_id": "2503.11918",
        "ref_s2_id": "s2-1",
        "ref_title": ref_title,
        "ref_authors": ["Ashish Vaswani"],
        "ref_submission_date": "2017-06-12",
        "ref_arxiv_id": ref_arxiv_id,
        "has_arxiv_id": bool(ref_arxiv_id),
        "ref_venue": "NeurIPS",
        "ref_year": 2017,
    }
    if ref_doi is not None:
        ref["ref_doi"] = ref_doi
    return ref


class TestExtractArxivId:
    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("https://arxiv.org/abs/2310.12345", "2310.12345"),
            ("http://arxiv.org/abs/1706.03762v2", "1706.03762"),
            ("https://export.arxiv.org/pdf/2310.12345v2.pdf", "2310.12345"),
            ("https://arxiv.org/pdf/1312.6114.pdf", "1312.6114"),
            ("https://arxiv.org/html/2401.12345v1", "2401.12345"),
            ("https://arxiv.org/abs/hep-th/9901001", "hep-th/9901001"),
            ("http://arxiv.org/pdf/hep-th/9901001v2.pdf", "hep-th/9901001"),
            ("https://arxiv.org/abs/math.GT/0309136v1", "math/0309136"),
            ("HTTP://ARXIV.ORG/ABS/CS/0601001v1", "cs/0601001"),
            ("https://doi.org/10.48550/arXiv.2401.17991", "2401.17991"),
            ("http://dx.doi.org/10.48550/arXiv.hep-th/9901001v2", "hep-th/9901001"),
            ("arXiv:2310.12345v2", "2310.12345"),
            ("https://arxiv.org/abs/1706.03762.", "1706.03762"),
            ("https://arxiv.org/pdf/2310.12345v2.pdf?download=1", "2310.12345"),
        ],
    )
    def test_valid_urls(self, url: str, expected: str) -> None:
        assert extract_arxiv_id_from_url(url) == expected

    @pytest.mark.parametrize(
        "url",
        [
            None,
            "",
            "   ",
            "http://dx.doi.org/10.1109/tro.2011.2159412",
            "https://api.semanticscholar.org/CorpusID:208958394",
            "https://example.com/abs/2310.12345",
            "https://notarxiv.org/abs/2310.12345",
            "https://my-arxiv.org/pdf/2310.12345.pdf",
            "https://arxiv.org/abs/2310.123456",
            "https://arxiv.org/abs/hep-th/99010012",
        ],
    )
    def test_non_arxiv_or_invalid_urls(self, url: Any) -> None:
        assert extract_arxiv_id_from_url(url) is None

    @pytest.mark.parametrize(
        ("doi", "expected"),
        [
            ("10.48550/arXiv.2310.12345", "2310.12345"),
            ("10.48550/ARXIV.2401.17991", "2401.17991"),
            ("https://doi.org/10.48550/arXiv.2310.12345v2", "2310.12345"),
            ("doi: 10.48550/arXiv.hep-th/9901001v2.", "hep-th/9901001"),
            ("10.1109/IROS58592.2024.10802738", None),
            (None, None),
            ("", None),
        ],
    )
    def test_doi_extraction(self, doi: Any, expected: str | None) -> None:
        assert extract_arxiv_id_from_doi(doi) == expected


class TestMatchByIdAndDoi:
    def test_match_url_with_version_pdf_and_old_id(self) -> None:
        candidates = [
            _make_ref("1706.03762"),
            _make_ref("hep-th/9901001"),
            _make_ref(None),
        ]
        e1 = _make_entry("vaswani", url="https://arxiv.org/pdf/1706.03762v2.pdf")
        e2 = _make_entry("witten", url="http://arxiv.org/abs/hep-th/9901001v3")

        r1 = match_entry(e1, candidates)
        r2 = match_entry(e2, candidates)

        assert r1 == {
            "arxiv_id": "2503.11918",
            "citation_key": "vaswani",
            "groundtruth_arxiv_id": "1706.03762",
            "method": "arxiv_url",
            "score": 1.0,
            "labeler": "auto",
        }
        assert r2["groundtruth_arxiv_id"] == "hep-th/9901001"
        assert r2["method"] == "arxiv_url"
        assert r2["score"] == 1.0

    def test_match_doi_arxiv_uppercase_even_with_doi_url(self) -> None:
        candidates = [_make_ref("2401.17991")]
        entry = _make_entry(
            "gpt_defeat",
            doi="10.48550/ARXIV.2401.17991",
            url="https://doi.org/10.48550/arXiv.2401.17991",
        )
        res = match_entry(entry, candidates)
        assert res["groundtruth_arxiv_id"] == "2401.17991"
        assert res["method"] == "doi"
        assert res["score"] == 1.0

    def test_match_doi_from_url_when_doi_field_empty(self) -> None:
        candidates = [_make_ref("2501.06210")]
        entry = _make_entry("aviation", doi=None, url="https://doi.org/10.48550/arXiv.2501.06210")
        res = match_entry(entry, candidates)
        assert res["groundtruth_arxiv_id"] == "2501.06210"
        assert res["method"] == "arxiv_url"
        assert res["score"] == 1.0

    def test_match_regular_doi_when_candidate_has_doi_and_noop_otherwise(self) -> None:
        entry = _make_entry("iros24", doi="https://doi.org/10.1109/IROS.2024.10")
        with_ref_doi = [_make_ref("2408.04054", ref_doi="10.1109/iros.2024.10")]
        without_ref_doi = [_make_ref("2408.04054")]

        hit = match_entry(entry, with_ref_doi)
        miss = match_entry(entry, without_ref_doi)

        assert hit["groundtruth_arxiv_id"] == "2408.04054"
        assert hit["method"] == "doi"
        assert miss == {
            "arxiv_id": "2503.11918",
            "citation_key": "iros24",
            "groundtruth_arxiv_id": None,
            "method": None,
            "score": None,
            "labeler": "auto",
        }

    def test_non_arxiv_url_and_missing_candidate_return_null(self) -> None:
        candidates = [_make_ref("1706.03762"), _make_ref(None)]
        entries = [
            _make_entry("s2_url", url="https://api.semanticscholar.org/CorpusID:123"),
            _make_entry("other_arxiv", url="https://arxiv.org/abs/9999.99999"),
            _make_entry("matched", url="https://arxiv.org/abs/1706.03762"),
        ]
        rows = label_entries(entries, candidates, pub_arxiv_id="2503.11918")
        assert len(rows) == 3
        assert rows[0]["groundtruth_arxiv_id"] is None
        assert rows[0]["method"] is None
        assert rows[0]["score"] is None
        assert rows[1]["groundtruth_arxiv_id"] is None
        assert rows[2]["groundtruth_arxiv_id"] == "1706.03762"


class TestPublicationIOAndAtomicWrite:
    def test_load_and_label_old_style_pub_id(self, tmp_path: Path) -> None:
        parsed_root = tmp_path / "parsed"
        corpus_root = tmp_path / "corpus"
        pub_dir_parsed = parsed_root / "hep-th_9901001"
        pub_dir_corpus = corpus_root / "hep-th_9901001"
        pub_dir_parsed.mkdir(parents=True)
        pub_dir_corpus.mkdir(parents=True)

        bib_rows = [
            _make_entry("k1", arxiv_id="hep-th/9901001", url="https://arxiv.org/abs/hep-th/9802150v1"),
            _make_entry("k2", arxiv_id="hep-th/9901001", url="https://example.org/paper"),
        ]
        (pub_dir_parsed / "bibtex.jsonl").write_text(
            "\n".join(json.dumps(r) for r in bib_rows) + "\n",
            encoding="utf-8",
        )
        ref_payload = {
            "arxiv_id": "hep-th/9901001",
            "crawled_at": "2026-10-29T17:45:25+07:00",
            "status": "ok",
            "n_total": 2,
            "n_with_arxiv": 1,
            "references": [
                _make_ref(None, ref_title="Non ArXiv Paper"),
                _make_ref("hep-th/9802150", ref_title="AdS/CFT"),
            ],
        }
        (pub_dir_corpus / "references.json").write_text(
            json.dumps(ref_payload),
            encoding="utf-8",
        )

        loaded_entries = load_bibtex_entries("hep-th/9901001v2", parsed_root=parsed_root)
        loaded_cands = load_arxiv_candidates("hep-th/9901001v2", corpus_root=corpus_root)
        assert loaded_entries is not None and len(loaded_entries) == 2
        assert loaded_cands is not None and len(loaded_cands) == 1
        assert loaded_cands[0]["ref_arxiv_id"] == "hep-th/9802150"

        labeled = label_publication("hep-th/9901001v2", parsed_root=parsed_root, corpus_root=corpus_root)
        assert labeled is not None
        assert [r["groundtruth_arxiv_id"] for r in labeled] == ["hep-th/9802150", None]
        assert labeled[0]["arxiv_id"] == "hep-th/9901001"

    def test_references_not_ok_returns_none(self, tmp_path: Path) -> None:
        corpus_root = tmp_path / "corpus"
        pub_dir = corpus_root / "2503-11914"
        pub_dir.mkdir(parents=True)
        (pub_dir / "references.json").write_text(
            json.dumps({"arxiv_id": "2503.11914", "status": "not_indexed", "references": []}),
            encoding="utf-8",
        )
        assert load_arxiv_candidates("2503.11914", corpus_root=corpus_root) is None

    def test_missing_or_empty_bibtex_file(self, tmp_path: Path) -> None:
        parsed_root = tmp_path / "parsed"
        assert load_bibtex_entries("2503.11914", parsed_root=parsed_root) is None

        pub_dir = parsed_root / "2503-11914"
        pub_dir.mkdir(parents=True)
        (pub_dir / "bibtex.jsonl").write_text("\n  \n", encoding="utf-8")
        assert load_bibtex_entries("2503.11914", parsed_root=parsed_root) == []

    def test_write_jsonl_atomic_preserves_target_on_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        out_file = tmp_path / "labels" / "auto" / "24120177.jsonl"
        initial = [{"arxiv_id": "2503.11918", "citation_key": "old", "groundtruth_arxiv_id": None}]
        write_jsonl_atomic(out_file, initial)
        assert not out_file.with_name(out_file.name + ".tmp").exists()
        assert [json.loads(line) for line in out_file.read_text(encoding="utf-8").splitlines()] == initial

        def _boom(_src: Path, _dst: Path) -> None:
            raise OSError("disk full")

        monkeypatch.setattr("matching.auto_label.os.replace", _boom)
        with pytest.raises(OSError, match="disk full"):
            write_jsonl_atomic(out_file, [{"citation_key": "new"}])

        assert not out_file.with_name(out_file.name + ".tmp").exists()
        assert [json.loads(line) for line in out_file.read_text(encoding="utf-8").splitlines()] == initial


class TestJournalAndOldIdFix:
    def test_journal_arxiv_preprint_matches(self) -> None:
        e = _make_entry("jr")
        e["journal"] = "arXiv preprint arXiv:1706.03762"
        r = match_entry(e, [_make_ref("1706.03762")])
        assert r["groundtruth_arxiv_id"] == "1706.03762"
        assert r["method"] == "arxiv_url"

    def test_journal_id_not_in_candidates_is_null(self) -> None:
        e = _make_entry("jr2")
        e["journal"] = "arXiv preprint arXiv:9999.99999"
        assert match_entry(e, [_make_ref("1706.03762")])["method"] is None

    def test_old_id_with_subcategory_matches_s2_form(self) -> None:
        e = _make_entry("old", url="https://arxiv.org/abs/math.GT/0309136")
        r = match_entry(e, [_make_ref("math/0309136")])
        assert r["groundtruth_arxiv_id"] == "math/0309136"
