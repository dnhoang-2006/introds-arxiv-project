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
    authors: Any = None,
    year: Any = 2017,
) -> dict[str, Any]:
    return {
        "arxiv_id": arxiv_id,
        "citation_key": citation_key,
        "entry_type": "article",
        "title": title,
        "authors": ["Vaswani, Ashish"] if authors is None else authors,
        "year": year,
        "doi": doi,
        "journal": None,
        "url": url,
    }


def _make_ref(
    ref_arxiv_id: str | None,
    *,
    ref_title: str | None = "Attention Is All You Need",
    ref_doi: str | None = None,
    ref_authors: Any = None,
    ref_year: Any = 2017,
) -> dict[str, Any]:
    ref: dict[str, Any] = {
        "arxiv_id": "2503.11918",
        "ref_s2_id": "s2-1",
        "ref_title": ref_title,
        "ref_authors": ["Ashish Vaswani"] if ref_authors is None else ref_authors,
        "ref_submission_date": "2017-06-12",
        "ref_arxiv_id": ref_arxiv_id,
        "has_arxiv_id": bool(ref_arxiv_id),
        "ref_venue": "NeurIPS",
        "ref_year": ref_year,
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

    def test_regular_doi_is_noop_because_s2_refs_have_no_doi(self) -> None:
        entry = _make_entry(
            "iros24",
            doi="https://doi.org/10.1109/IROS.2024.10",
            title="Distinct Entry Title Without Title Match",
        )
        res = match_entry(entry, [_make_ref("2408.04054", ref_doi="10.1109/iros.2024.10")])
        assert res["groundtruth_arxiv_id"] is None
        assert res["method"] is None
        assert res["score"] is None

    def test_non_arxiv_url_and_missing_candidate_return_null(self) -> None:
        candidates = [_make_ref("1706.03762"), _make_ref(None)]
        entries = [
            _make_entry(
                "s2_url",
                url="https://api.semanticscholar.org/CorpusID:123",
                title="Unrelated S2 Paper",
            ),
            _make_entry(
                "other_arxiv",
                url="https://arxiv.org/abs/9999.99999",
                title="Unrelated Other Arxiv Paper",
            ),
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
        e = _make_entry("jr2", title="Completely Different Journal Paper")
        e["journal"] = "arXiv preprint arXiv:9999.99999"
        assert match_entry(e, [_make_ref("1706.03762")])["method"] is None

    def test_old_id_with_subcategory_matches_s2_form(self) -> None:
        e = _make_entry("old", url="https://arxiv.org/abs/math.GT/0309136")
        r = match_entry(e, [_make_ref("math/0309136")])
        assert r["groundtruth_arxiv_id"] == "math/0309136"


class TestAuthorYearFilterAndTitleMatch:
    def test_latex_accents_and_braces_in_title_and_author(self) -> None:
        entry = _make_entry(
            "bezier02",
            title="B\\'ezier and {B}-spline {T}echniques for Surface Design",
            authors=['{\\"O}sterberg, Jan', "Paluszny, Marco"],
            year="2002",
        )
        candidates = [
            _make_ref(
                "0201.1234",
                ref_title="Bézier and B-spline Techniques for Surface Design",
                ref_authors=["Jan Österberg", "Marco Paluszny"],
                ref_year=2002,
            )
        ]
        res = match_entry(entry, candidates)
        assert res["groundtruth_arxiv_id"] == "0201.1234"
        assert res["method"] == "title"
        assert res["score"] == 1.0

    @pytest.mark.parametrize(
        ("entry_authors", "ref_authors", "should_match"),
        [
            (["Ben Amor, Heni"], ["H. Ben Amor"], True),
            (["H. Ben Amor"], ["Ben Amor, Heni"], True),
            (["Khansari-Zadeh, S. Mohammad"], ["S. Mohammad Khansari Zadeh"], True),
            (["Li, Wei"], ["Reza Ali"], False),
        ],
    )
    def test_asymmetric_multiword_surname_matching(
        self,
        entry_authors: list[str],
        ref_authors: list[str],
        should_match: bool,
    ) -> None:
        title = "A Comparison of Imitation Learning Algorithms for Manipulation"
        entry = _make_entry("amor24", title=title, authors=entry_authors, year=2024)
        cands = [_make_ref("2408.06536", ref_title=title, ref_authors=ref_authors, ref_year=2024)]
        res = match_entry(entry, cands)
        if should_match:
            assert res["groundtruth_arxiv_id"] == "2408.06536"
            assert res["method"] == "title"
        else:
            assert res["groundtruth_arxiv_id"] is None
            assert res["method"] is None

    def test_short_title_requires_affirmative_first_author_match(self) -> None:
        cands_with_author = [
            _make_ref("1601.00001", ref_title="Deep Learning", ref_authors=["Ian Goodfellow"], ref_year=2016)
        ]
        cands_no_author = [
            _make_ref("1601.00001", ref_title="Deep Learning", ref_authors=[], ref_year=2016)
        ]
        e_with_author = _make_entry("dl", title="Deep Learning", authors=["Goodfellow, Ian"], year=2016)
        e_no_author = _make_entry("dl_noauth", title="Deep Learning", authors=[], year=2016)
        e_three_words = _make_entry("nerf", title="Neural Radiance Fields", authors=[], year=2020)
        cands_nerf = [
            _make_ref("2003.08934", ref_title="Neural Radiance Fields", ref_authors=["Ben Mildenhall"], ref_year=2020)
        ]

        hit = match_entry(e_with_author, cands_with_author)
        assert hit["groundtruth_arxiv_id"] == "1601.00001"
        assert hit["method"] == "title"

        assert match_entry(e_with_author, cands_no_author)["groundtruth_arxiv_id"] is None
        assert match_entry(e_no_author, cands_with_author)["groundtruth_arxiv_id"] is None
        assert match_entry(e_three_words, cands_nerf)["groundtruth_arxiv_id"] is None

    def test_close_candidates_respect_margin_and_filter(self) -> None:
        entry = _make_entry(
            "gnn",
            title="Graph Neural Networks for Molecular Property Prediction",
            authors=["Wu, Zhenqin"],
            year=2023,
        )
        # Hai ứng viên đều qua vòng lọc tác giả+năm, score ~1.00 vs ~0.99 (< margin 0.03)
        ambiguous = [
            _make_ref(
                "2301.00001",
                ref_title="Graph Neural Networks for Molecular Property Prediction",
                ref_authors=["Zhenqin Wu"],
                ref_year=2023,
            ),
            _make_ref(
                "2301.00002",
                ref_title="Graph Neural Networks for Molecular Property Predictions",
                ref_authors=["Zhenqin Wu"],
                ref_year=2023,
            ),
        ]
        assert match_entry(entry, ambiguous)["groundtruth_arxiv_id"] is None

        # Khi ứng viên gây nhiễu bị loại bởi lọc tác giả hoặc năm, ứng viên đúng phải khớp
        filtered_disambiguates = [
            _make_ref(
                "2301.00001",
                ref_title="Graph Neural Networks for Molecular Property Prediction",
                ref_authors=["Zhenqin Wu"],
                ref_year=2023,
            ),
            _make_ref(
                "2301.00002",
                ref_title="Graph Neural Networks for Molecular Property Predictions",
                ref_authors=["Other Author"],
                ref_year=2023,
            ),
        ]
        res = match_entry(entry, filtered_disambiguates)
        assert res["groundtruth_arxiv_id"] == "2301.00001"
        assert res["method"] == "title"

        # Khi khoảng cách đủ lớn (>= 0.03), vẫn chọn ứng viên tốt nhất
        clear_margin = [
            _make_ref(
                "2301.00001",
                ref_title="Graph Neural Networks for Molecular Property Prediction",
                ref_authors=["Zhenqin Wu"],
                ref_year=2023,
            ),
            _make_ref(
                "2301.00003",
                ref_title="Graph Neural Networks for Molecular Property Analysis",
                ref_authors=["Zhenqin Wu"],
                ref_year=2023,
            ),
        ]
        res2 = match_entry(entry, clear_margin)
        assert res2["groundtruth_arxiv_id"] == "2301.00001"
        assert res2["score"] == 1.0

    def test_duplicate_candidate_same_arxiv_id_does_not_block_itself(self) -> None:
        title = "Learning Stable Nonlinear Dynamical Systems With Gaussian Mixture Models"
        entry = _make_entry("khansari", title=title, authors=["Khansari-Zadeh, S."], year=2011)
        cands = [
            _make_ref("1101.00001", ref_title=title, ref_authors=["S. Khansari-Zadeh"], ref_year=2011),
            _make_ref("1101.00001", ref_title=title, ref_authors=["S. Khansari-Zadeh"], ref_year=2011),
        ]
        res = match_entry(entry, cands)
        assert res["groundtruth_arxiv_id"] == "1101.00001"
        assert res["method"] == "title"

    def test_year_delta_and_author_year_never_match_alone(self) -> None:
        title = "Scaling Learning Algorithms Towards Artificial Intelligence"
        entry_2024 = _make_entry("y24", title=title, authors=["Bengio, Yoshua"], year=2024)
        cand_2023 = _make_ref("2305.00001", ref_title=title, ref_authors=["Yoshua Bengio"], ref_year=2023)
        cand_2022 = _make_ref("2205.00001", ref_title=title, ref_authors=["Yoshua Bengio"], ref_year=2022)

        assert match_entry(entry_2024, [cand_2023])["groundtruth_arxiv_id"] == "2305.00001"
        assert match_entry(entry_2024, [cand_2022])["groundtruth_arxiv_id"] is None

        # Khớp hệt tác giả và năm nhưng khác tiêu đề -> không được tự gán nhãn
        wrong_title = _make_entry(
            "same_auth_yr",
            title="Completely Unrelated Survey on Robotics",
            authors=["Bengio, Yoshua"],
            year=2023,
        )
        assert match_entry(wrong_title, [cand_2023])["groundtruth_arxiv_id"] is None

    def test_missing_fields_handling(self) -> None:
        long_title = "Auto-Encoding Variational Bayes for Representation Learning"
        # Thiếu author và year ở entry/ref với title đủ dài -> không loại oan
        e_missing_ay = _make_entry("k1", title=long_title, authors=None, year=None)
        c_missing_ay = _make_ref("1312.6114", ref_title=long_title, ref_authors=[], ref_year=None)
        assert match_entry(e_missing_ay, [c_missing_ay])["groundtruth_arxiv_id"] == "1312.6114"

        # Entry thiếu title -> không khớp
        e_no_title = _make_entry("k2", title=None, authors=["Kingma, Diederik"], year=2013)
        assert match_entry(e_no_title, [c_missing_ay])["groundtruth_arxiv_id"] is None

        # Reference thiếu ref_title không làm crash và không cản các reference hợp lệ khác
        c_no_title = _make_ref("9999.00001", ref_title=None, ref_authors=["Someone"], ref_year=2013)
        res = match_entry(
            _make_entry("k3", title=long_title, authors=["Kingma, Diederik"], year=2013),
            [c_no_title, c_missing_ay],
        )
        assert res["groundtruth_arxiv_id"] == "1312.6114"

    def test_title_threshold_boundary_and_id_priority_over_title(self) -> None:
        c_url = _make_ref(
            "2101.00001",
            ref_title="Completely Unrelated Reference Title For Id Priority",
            ref_authors=["Alice Smith"],
            ref_year=2021,
        )
        c_title = _make_ref(
            "2101.00002",
            ref_title="Contrastive Representation Learning for Graph Classification Tasks",
            ref_authors=["Bob Jones"],
            ref_year=2021,
        )
        # Bước 1 (URL) phải thắng và dừng trước khi sang bước title
        e_priority = _make_entry(
            "prio",
            url="https://arxiv.org/abs/2101.00001",
            title="Contrastive Representation Learning for Graph Classification Tasks",
            authors=["Jones, Bob"],
            year=2021,
        )
        res_prio = match_entry(e_priority, [c_url, c_title])
        assert res_prio["groundtruth_arxiv_id"] == "2101.00001"
        assert res_prio["method"] == "arxiv_url"

        # Score ~0.87: bị loại ở ngưỡng mặc định 0.90, khớp khi hạ ngưỡng xuống 0.85
        e_near = _make_entry(
            "near_thresh",
            title="Contrastive Learning for Graph Classification Tasks",
            authors=["Jones, Bob"],
            year=2021,
        )
        assert match_entry(e_near, [c_title])["groundtruth_arxiv_id"] is None
        res_relaxed = match_entry(e_near, [c_title], title_threshold=0.85)
        assert res_relaxed["groundtruth_arxiv_id"] == "2101.00002"
        assert res_relaxed["method"] == "title"
        assert 0.85 <= res_relaxed["score"] < 0.90


class TestGarbledAuthors:
    GARBLED = ["ibfieldauthor ibinfopersonNational Institute of Standards"]
    TITLE = "Quantum sensitivity of parametric oscillators in noisy regimes"

    def _ref(self, title: str, year: int = 2020, aid: str = "2001.00001") -> dict[str, Any]:
        r = _make_ref(aid)
        r["ref_title"] = title
        r["ref_authors"] = ["Alice Smith"]
        r["ref_year"] = year
        return r

    def _entry(self, title: str) -> dict[str, Any]:
        e = _make_entry("g", title=title)
        e["authors"] = self.GARBLED
        e["year"] = 2020
        return e

    def test_garbled_author_still_matches_exact_long_title(self) -> None:
        res = match_entry(self._entry(self.TITLE), [self._ref(self.TITLE)])
        assert res["groundtruth_arxiv_id"] == "2001.00001"
        assert res["method"] == "title"

    def test_garbled_author_needs_stricter_threshold(self) -> None:
        near = self.TITLE.replace("noisy regimes", "noisy regime")  # ~0.98 vs 0.90-0.95 vùng nhạy
        weaker = "Quantum sensitivity of parametric oscillators"  # ratio < 0.95
        assert match_entry(self._entry(self.TITLE), [self._ref(near)])["method"] == "title"
        assert match_entry(self._entry(self.TITLE), [self._ref(weaker)])["method"] is None

    def test_garbled_author_never_matches_short_title(self) -> None:
        res = match_entry(self._entry("Deep nets"), [self._ref("Deep nets")])
        assert res["method"] is None
