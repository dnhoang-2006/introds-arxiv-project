from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

SRC_DIR = str(Path(__file__).resolve().parent.parent / "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import config  # noqa: E402
import matching.auto_label as auto_label_mod  # noqa: E402
from matching.auto_label import (  # noqa: E402
    evaluate_gold,
    extract_arxiv_id_from_doi,
    extract_arxiv_id_from_url,
    label_entries,
    label_publication,
    load_arxiv_candidates,
    load_bibtex_entries,
    load_exclude_ids,
    main,
    match_entry,
    run_auto_label,
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
            "labeler": "auto",
            "method": "auto",
            "rule": "arxiv_url",
            "score": 1.0,
        }
        assert r2["groundtruth_arxiv_id"] == "hep-th/9901001"
        assert r2["labeler"] == "auto"
        assert r2["method"] == "auto"
        assert r2["rule"] == "arxiv_url"
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
        assert res["method"] == "auto"
        assert res["rule"] == "doi"
        assert res["score"] == 1.0

    def test_match_doi_from_url_when_doi_field_empty(self) -> None:
        candidates = [_make_ref("2501.06210")]
        entry = _make_entry("aviation", doi=None, url="https://doi.org/10.48550/arXiv.2501.06210")
        res = match_entry(entry, candidates)
        assert res["groundtruth_arxiv_id"] == "2501.06210"
        assert res["method"] == "auto"
        assert res["rule"] == "arxiv_url"
        assert res["score"] == 1.0

    def test_regular_doi_is_noop_because_s2_refs_have_no_doi(self) -> None:
        entry = _make_entry(
            "iros24",
            doi="https://doi.org/10.1109/IROS.2024.10",
            title="Distinct Entry Title Without Title Match",
        )
        res = match_entry(entry, [_make_ref("2408.04054", ref_doi="10.1109/iros.2024.10")])
        assert res["groundtruth_arxiv_id"] is None
        assert res["method"] == "auto"
        assert res["rule"] is None
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
        assert rows[0]["method"] == "auto"
        assert rows[0]["rule"] is None
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
        assert r["rule"] == "arxiv_url"

    def test_journal_id_not_in_candidates_is_null(self) -> None:
        e = _make_entry("jr2", title="Completely Different Journal Paper")
        e["journal"] = "arXiv preprint arXiv:9999.99999"
        assert match_entry(e, [_make_ref("1706.03762")])["rule"] is None

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
        assert res["rule"] == "title"
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
            assert res["rule"] == "title"
        else:
            assert res["groundtruth_arxiv_id"] is None
            assert res["rule"] is None

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
        assert hit["rule"] == "title"

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
        assert res["rule"] == "title"

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
        assert res["rule"] == "title"

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
        assert res_prio["method"] == "auto"
        assert res_prio["rule"] == "arxiv_url"

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
        assert res_relaxed["method"] == "auto"
        assert res_relaxed["rule"] == "title"
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
        assert res["rule"] == "title"

    def test_garbled_author_needs_stricter_threshold(self) -> None:
        near = self.TITLE.replace("noisy regimes", "noisy regime")  # ~0.98 vs 0.90-0.95 vùng nhạy
        weaker = "Quantum sensitivity of parametric oscillators"  # ratio < 0.95
        assert match_entry(self._entry(self.TITLE), [self._ref(near)])["rule"] == "title"
        assert match_entry(self._entry(self.TITLE), [self._ref(weaker)])["rule"] is None

    def test_garbled_author_never_matches_short_title(self) -> None:
        res = match_entry(self._entry("Deep nets"), [self._ref("Deep nets")])
        assert res["rule"] is None


def _write_pub_fixture(
    parsed_root: Path,
    corpus_root: Path,
    arxiv_id: str,
    entries: list[dict[str, Any]],
    refs: list[dict[str, Any]],
    *,
    status: str = "ok",
) -> None:
    pk = config.pub_key(arxiv_id)
    (parsed_root / pk).mkdir(parents=True, exist_ok=True)
    (corpus_root / pk).mkdir(parents=True, exist_ok=True)
    (parsed_root / pk / "bibtex.jsonl").write_text(
        "".join(json.dumps(e) + "\n" for e in entries),
        encoding="utf-8",
    )
    (corpus_root / pk / "references.json").write_text(
        json.dumps(
            {
                "arxiv_id": arxiv_id,
                "crawled_at": "2026-10-29T17:45:25+07:00",
                "status": status,
                "n_total": len(refs),
                "n_with_arxiv": sum(1 for r in refs if r.get("ref_arxiv_id")),
                "references": refs,
            }
        ),
        encoding="utf-8",
    )


class TestCLIAndEval:
    def test_sample_selection_filters_seed_dry_run_and_overwrite(self, tmp_path: Path) -> None:
        parsed_root = tmp_path / "parsed"
        corpus_root = tmp_path / "corpus"
        out_dir = tmp_path / "labels" / "auto"

        # 2 pub hợp lệ (giống mẫu nhỏ chuẩn + 1 bài vừa đúng 1000 entry)
        _write_pub_fixture(
            parsed_root,
            corpus_root,
            "2503.00001",
            [
                _make_entry("k1", arxiv_id="2503.00001", url="https://arxiv.org/abs/1706.03762"),
                _make_entry("k2", arxiv_id="2503.00001", title="No Match Title Here"),
            ],
            [_make_ref("1706.03762")],
        )
        _write_pub_fixture(
            parsed_root,
            corpus_root,
            "2503.00002",
            [
                _make_entry("k1", arxiv_id="2503.00002", doi="10.48550/ARXIV.2401.17991")
                if i == 0
                else _make_entry(f"extra_{i}", arxiv_id="2503.00002", title=f"Unmatched Paper {i}")
                for i in range(1000)
            ],
            [_make_ref("2401.17991", ref_title="GPT Defeaters Analysis")],
        )
        # Pub bị loại do: excluded, not_ok, no_arxiv_cand, no_bibtex, >1000 entries
        _write_pub_fixture(
            parsed_root,
            corpus_root,
            "2503.00003",
            [_make_entry("k1", arxiv_id="2503.00003", url="https://arxiv.org/abs/1706.03762")],
            [_make_ref("1706.03762")],
        )
        _write_pub_fixture(
            parsed_root,
            corpus_root,
            "2503.00004",
            [_make_entry("k1", arxiv_id="2503.00004")],
            [_make_ref("1706.03762")],
            status="not_indexed",
        )
        _write_pub_fixture(
            parsed_root,
            corpus_root,
            "2503.00005",
            [_make_entry("k1", arxiv_id="2503.00005")],
            [_make_ref(None)],
        )
        _write_pub_fixture(
            parsed_root,
            corpus_root,
            "2503.00006",
            [],
            [_make_ref("1706.03762")],
        )
        _write_pub_fixture(
            parsed_root,
            corpus_root,
            "2503.00007",
            [_make_entry(f"b_{i}", arxiv_id="2503.00007") for i in range(1001)],
            [_make_ref("1706.03762")],
        )

        ids_file = tmp_path / "ids.txt"
        ids_file.write_text(
            "# comment\narXiv:2503.00001v2\n2503.00002\n2503.00003\n2503.00004\n"
            "2503.00005\n2503.00006\n2503.00007\n2503.00008\n2503.00001\n",
            encoding="utf-8",
        )
        exclude_file = tmp_path / "manual.jsonl"
        exclude_file.write_text(
            json.dumps({"arxiv_id": "2503.00003", "citation_key": "k1", "groundtruth_arxiv_id": "1706.03762"}) + "\n",
            encoding="utf-8",
        )

        # --dry-run không ghi file ra đĩa
        dry = run_auto_label(
            ids_path=ids_file,
            mssv="24120177",
            n=5,
            seed=42,
            exclude_path=exclude_file,
            dry_run=True,
            parsed_root=parsed_root,
            corpus_root=corpus_root,
            out_dir=out_dir,
        )
        assert dry["skipped"] is False
        assert dry["meta"]["n_selected"] == 2
        assert dry["meta"]["eligibility"] == {
            "total_ids": 8,
            "excluded_manual": 1,
            "references_missing": 1,
            "references_not_ok": 1,
            "no_arxiv_candidates": 1,
            "bibtex_missing": 0,
            "no_bibtex_entries": 1,
            "too_many_bibtex_entries": 1,
            "eligible": 2,
        }
        assert not (out_dir / "24120177.jsonl").exists()
        assert not (out_dir / "24120177.pubs.json").exists()

        # Chạy thật tạo .jsonl và .pubs.json, kiểm tra tính tất định và idempotent
        real = run_auto_label(
            ids_path=ids_file,
            mssv="24120177",
            n=5,
            seed=42,
            exclude_path=exclude_file,
            parsed_root=parsed_root,
            corpus_root=corpus_root,
            out_dir=out_dir,
        )
        assert real["skipped"] is False
        jsonl_lines = (out_dir / "24120177.jsonl").read_text(encoding="utf-8").splitlines()
        pubs_json = json.loads((out_dir / "24120177.pubs.json").read_text(encoding="utf-8"))
        assert len(jsonl_lines) == 1002
        parsed_rows = [json.loads(ln) for ln in jsonl_lines]
        assert all(r["method"] == "auto" and r["labeler"] == "24120177" for r in parsed_rows)
        assert pubs_json["summary"]["total_entries"] == 1002
        assert pubs_json["summary"]["total_matched"] == 2
        assert pubs_json["summary"]["rules"] == {"arxiv_url": 1, "doi": 1, "null": 1000}
        assert {p["arxiv_id"] for p in pubs_json["publications"]} == {"2503.00001", "2503.00002"}
        assert "2503.00003" not in {p["arxiv_id"] for p in pubs_json["publications"]}
        assert [p["arxiv_id"] for p in pubs_json["publications"]] == [
            p["arxiv_id"] for p in dry["meta"]["publications"]
        ]

        from matching.label_io import load_labels

        loaded_labels = load_labels(out_dir.parent)
        assert len(loaded_labels) == 1002
        assert loaded_labels[("2503.00001", "k1")].method == "auto"
        assert loaded_labels[("2503.00001", "k1")].labeler == "24120177"
        assert loaded_labels[("2503.00001", "k1")].groundtruth_arxiv_id == "1706.03762"
        assert loaded_labels[("2503.00001", "k2")].method == "auto"
        assert loaded_labels[("2503.00001", "k2")].labeler == "24120177"
        assert loaded_labels[("2503.00001", "k2")].groundtruth_arxiv_id is None

        # Không có --overwrite phải bỏ qua và không ghi đè
        (out_dir / "24120177.jsonl").write_text("SENTINEL\n", encoding="utf-8")
        skipped = run_auto_label(
            ids_path=ids_file,
            mssv="24120177",
            n=5,
            seed=42,
            exclude_path=exclude_file,
            parsed_root=parsed_root,
            corpus_root=corpus_root,
            out_dir=out_dir,
        )
        assert skipped["skipped"] is True
        assert (out_dir / "24120177.jsonl").read_text(encoding="utf-8") == "SENTINEL\n"

        # Có --overwrite phải ghi đè lại đúng số dòng
        overwritten = run_auto_label(
            ids_path=ids_file,
            mssv="24120177",
            n=5,
            seed=42,
            exclude_path=exclude_file,
            overwrite=True,
            parsed_root=parsed_root,
            corpus_root=corpus_root,
            out_dir=out_dir,
        )
        assert overwritten["skipped"] is False
        assert len((out_dir / "24120177.jsonl").read_text(encoding="utf-8").splitlines()) == 1002

    def test_load_exclude_formats_and_missing_raises(self, tmp_path: Path) -> None:
        txt_f = tmp_path / "ex.txt"
        txt_f.write_text("# header\n2503.00001v2\narXiv:hep-th/9901001\n", encoding="utf-8")
        assert load_exclude_ids(txt_f) == {"2503.00001", "hep-th/9901001"}

        json_f = tmp_path / "ex.pubs.json"
        json_f.write_text(json.dumps({"publications": [{"arxiv_id": "2503.00002"}]}), encoding="utf-8")
        assert load_exclude_ids(json_f) == {"2503.00002"}

        json_list_f = tmp_path / "ex_list.json"
        json_list_f.write_text(json.dumps([{"arxiv_id": "2503.00003"}, {"arxiv_id": None}]), encoding="utf-8")
        assert load_exclude_ids(json_list_f) == {"2503.00003"}

        with pytest.raises(FileNotFoundError):
            load_exclude_ids(tmp_path / "does_not_exist.txt")

    def test_evaluate_gold_precision_recall_by_rule_and_zero_division(self, tmp_path: Path) -> None:
        parsed_root = tmp_path / "parsed"
        corpus_root = tmp_path / "corpus"

        _write_pub_fixture(
            parsed_root,
            corpus_root,
            "2503.10001",
            [
                _make_entry("e_url", arxiv_id="2503.10001", url="https://arxiv.org/abs/1706.03762"),
                _make_entry("e_doi", arxiv_id="2503.10001", doi="10.48550/ARXIV.2401.17991"),
                _make_entry(
                    "e_title_ok",
                    arxiv_id="2503.10001",
                    title="Neural Radiance Fields for View Synthesis in Practice",
                    authors=["Mildenhall, Ben"],
                    year=2020,
                ),
                _make_entry(
                    "e_title_fp",
                    arxiv_id="2503.10001",
                    title="Graph Representation Learning for Molecules",
                    authors=["Smith, Alice"],
                    year=2021,
                ),
                _make_entry("e_miss", arxiv_id="2503.10001", title="Completely Different Manual Entry"),
                _make_entry("e_extra", arxiv_id="2503.10001", url="https://arxiv.org/abs/2001.00001"),
            ],
            [
                _make_ref("1706.03762", ref_title="Attention"),
                _make_ref("2401.17991", ref_title="GPT Defeaters"),
                _make_ref(
                    "2003.08934",
                    ref_title="Neural Radiance Fields for View Synthesis in Practice",
                    ref_authors=["Ben Mildenhall"],
                    ref_year=2020,
                ),
                _make_ref(
                    "2101.99999",
                    ref_title="Graph Representation Learning for Molecules",
                    ref_authors=["Alice Smith"],
                    ref_year=2021,
                ),
                _make_ref("2001.00001", ref_title="Extra Unlisted Paper"),
            ],
        )

        gold_file = tmp_path / "gold.jsonl"
        gold_rows = [
            {"arxiv_id": "2503.10001", "citation_key": "e_url", "groundtruth_arxiv_id": "1706.03762"},
            {"arxiv_id": "2503.10001", "citation_key": "e_doi", "groundtruth_arxiv_id": "2401.17991"},
            {"arxiv_id": "2503.10001", "citation_key": "e_title_ok", "groundtruth_arxiv_id": "2003.08934"},
            {"arxiv_id": "2503.10001", "citation_key": "e_title_fp", "groundtruth_arxiv_id": "2101.11111"},  # FP
            {"arxiv_id": "2503.10001", "citation_key": "e_miss", "groundtruth_arxiv_id": "1901.00001"},  # FN
            {"arxiv_id": "2503.10001", "citation_key": "e_null_in_gold", "groundtruth_arxiv_id": None},  # không tính vào Q
        ]
        gold_file.write_text("".join(json.dumps(r) + "\n" for r in gold_rows), encoding="utf-8")

        ev = evaluate_gold(gold_file, parsed_root=parsed_root, corpus_root=corpus_root)
        assert ev["n_gold_pubs"] == 1
        assert ev["n_evaluated_pubs"] == 1
        assert ev["n_gold_positive"] == 5
        assert ev["auto_matched_on_gold"] == 4
        assert ev["correct_on_gold"] == 3
        assert ev["auto_matched_unlisted"] == 1
        assert ev["precision"] == 0.75
        assert ev["recall"] == 0.6
        assert ev["by_rule"]["arxiv_url"] == {"matched": 1, "correct": 1, "precision": 1.0, "recall_share": 0.2}
        assert ev["by_rule"]["doi"] == {"matched": 1, "correct": 1, "precision": 1.0, "recall_share": 0.2}
        assert ev["by_rule"]["title"] == {"matched": 2, "correct": 1, "precision": 0.5, "recall_share": 0.2}

        # Trường hợp không có cặp khớp nào -> precision là None, không chia cho 0
        empty_gold = tmp_path / "empty_gold.jsonl"
        empty_gold.write_text(
            json.dumps({"arxiv_id": "2503.10001", "citation_key": "e_miss", "groundtruth_arxiv_id": "1901.00001"}) + "\n",
            encoding="utf-8",
        )
        ev_zero = evaluate_gold(empty_gold, parsed_root=parsed_root, corpus_root=corpus_root)
        assert ev_zero["auto_matched_on_gold"] == 0
        assert ev_zero["precision"] is None
        assert ev_zero["recall"] == 0.0

        # Entry được gold đánh dấu null nhưng matcher gán nhầm -> tính vào mẫu số precision (FP)
        null_fp_gold = tmp_path / "null_fp_gold.jsonl"
        null_fp_gold.write_text(
            json.dumps({"arxiv_id": "2503.10001", "citation_key": "e_url", "groundtruth_arxiv_id": None}) + "\n",
            encoding="utf-8",
        )
        ev_null_fp = evaluate_gold(null_fp_gold, parsed_root=parsed_root, corpus_root=corpus_root)
        assert ev_null_fp["n_gold_positive"] == 0
        assert ev_null_fp["auto_matched_on_gold"] == 1
        assert ev_null_fp["correct_on_gold"] == 0
        assert ev_null_fp["precision"] == 0.0
        assert ev_null_fp["recall"] is None

    def test_cli_main_validation_and_eval_output(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        parsed_root = tmp_path / "parsed"
        corpus_root = tmp_path / "corpus"
        labels_root = tmp_path / "labels"

        _write_pub_fixture(
            parsed_root,
            corpus_root,
            "2503.20001",
            [_make_entry("k1", arxiv_id="2503.20001", url="https://arxiv.org/abs/1706.03762")],
            [_make_ref("1706.03762")],
        )
        ids_file = tmp_path / "ids.txt"
        ids_file.write_text("2503.20001\n", encoding="utf-8")
        gold_file = tmp_path / "gold.jsonl"
        gold_file.write_text(
            json.dumps({"arxiv_id": "2503.20001", "citation_key": "k1", "groundtruth_arxiv_id": "1706.03762"}) + "\n",
            encoding="utf-8",
        )

        monkeypatch.setattr(auto_label_mod, "PARSED_ROOT", parsed_root)
        monkeypatch.setattr(auto_label_mod, "LABELS_ROOT", labels_root)
        monkeypatch.setattr(config, "CORPUS_ROOT", corpus_root)

        main(["--ids", str(ids_file), "--mssv", "24120177", "--n", "1", "--seed", "42"])
        out_run = capsys.readouterr().out
        assert "Chọn 1/1 pub" in out_run
        assert (labels_root / "auto" / "24120177.jsonl").is_file()
        assert (labels_root / "auto" / "24120177.pubs.json").is_file()

        main(["--eval", "--gold", str(gold_file)])
        out_eval = capsys.readouterr().out
        assert "Precision (cặp matcher gán): 100.00% (1/1)" in out_eval
        assert "Recall    (cặp gold):        100.00% (1/1)" in out_eval
        assert "Theo rule:" in out_eval
        assert "arxiv_url" in out_eval

        with pytest.raises(SystemExit):
            main(["--eval"])
        with pytest.raises(SystemExit):
            main(["--ids", str(ids_file), "--mssv", "../bad", "--n", "1"])
        with pytest.raises(SystemExit):
            main(["--ids", str(ids_file), "--mssv", "24120177", "--exclude", str(tmp_path / "missing.txt")])


class TestSkipReportsExistingSize:
    def test_skip_returns_existing_n_selected_and_warns_mismatch(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        ids = tmp_path / "ids.txt"
        ids.write_text("2503.11918", encoding="utf-8")
        out = tmp_path / "out"
        out.mkdir()
        (out / "24120177.jsonl").write_text("", encoding="utf-8")
        (out / "24120177.pubs.json").write_text('{"n_selected": 5}', encoding="utf-8")
        res = run_auto_label(
            ids_path=ids,
            mssv="24120177",
            n=500,
            out_dir=out,
            parsed_root=tmp_path,
            corpus_root=tmp_path,
        )
        assert res["skipped"] is True
        assert res["existing_n_selected"] == 5
        assert res["n_requested"] == 500

        monkeypatch.setattr(auto_label_mod, "LABELS_ROOT", tmp_path / "lbl")
        lbl_auto = tmp_path / "lbl" / "auto"
        lbl_auto.mkdir(parents=True)
        (lbl_auto / "24120177.jsonl").write_text("", encoding="utf-8")
        (lbl_auto / "24120177.pubs.json").write_text('{"n_selected": 5}', encoding="utf-8")
        main(["--ids", str(ids), "--mssv", "24120177", "--n", "500"])
        out_txt = capsys.readouterr().out
        assert "5 pub nhưng đang yêu cầu 500 pub" in out_txt


class TestZeroMatchedSummaryAndMissingGold:
    def test_zero_matched_pub_counted_in_summary_and_warned(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        parsed_root = tmp_path / "parsed"
        corpus_root = tmp_path / "corpus"
        _write_pub_fixture(
            parsed_root,
            corpus_root,
            "2503.30001",
            [_make_entry("k1", arxiv_id="2503.30001", url="https://arxiv.org/abs/1706.03762")],
            [_make_ref("1706.03762")],
        )
        _write_pub_fixture(
            parsed_root,
            corpus_root,
            "2503.30002",
            [_make_entry("k2", arxiv_id="2503.30002", title=None)],
            [_make_ref("1706.03762")],
        )
        ids_file = tmp_path / "ids.txt"
        ids_file.write_text("2503.30001\n2503.30002\n", encoding="utf-8")
        res = run_auto_label(
            ids_path=ids_file,
            mssv="24120177",
            n=2,
            seed=42,
            dry_run=True,
            parsed_root=parsed_root,
            corpus_root=corpus_root,
        )
        summ = res["meta"]["summary"]
        assert summ["n_pubs_with_matches"] == 1
        assert summ["n_pubs_zero_matched"] == 1
        auto_label_mod._print_run_summary(res)
        assert "n_matched=0" in capsys.readouterr().out

    def test_eval_missing_pubs_does_not_penalize_recall_and_cli_roots(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        parsed_root = tmp_path / "custom_parsed"
        corpus_root = tmp_path / "custom_corpus"
        _write_pub_fixture(
            parsed_root,
            corpus_root,
            "2503.40001",
            [_make_entry("k1", arxiv_id="2503.40001", url="https://arxiv.org/abs/1706.03762")],
            [_make_ref("1706.03762")],
        )
        # Pub thứ hai có trong gold nhưng không có trên đĩa
        gold_file = tmp_path / "mixed_gold.jsonl"
        gold_rows = [
            {"arxiv_id": "2503.40001", "citation_key": "k1", "groundtruth_arxiv_id": "1706.03762"},
            {"arxiv_id": "2507.99999", "citation_key": "k2", "groundtruth_arxiv_id": "1810.04805"},
        ]
        gold_file.write_text("".join(json.dumps(r) + "\n" for r in gold_rows), encoding="utf-8")

        ev = evaluate_gold(gold_file, parsed_root=parsed_root, corpus_root=corpus_root)
        assert ev["n_gold_pubs"] == 2
        assert ev["n_evaluated_pubs"] == 1
        assert ev["missing_pubs"] == ["2507.99999"]
        assert ev["missing_pub_details"] == {
            "2507.99999": ["bibtex_missing_or_invalid", "references_missing"]
        }
        assert ev["n_gold_positive"] == 2
        assert ev["n_gold_positive_evaluated"] == 1
        assert ev["precision"] == 1.0
        assert ev["recall"] == 1.0
        assert ev["by_rule"]["arxiv_url"]["recall_share"] == 1.0

        # Kiểm tra CLI --parsed-root và --corpus-root trực tiếp
        main([
            "--eval",
            "--gold", str(gold_file),
            "--parsed-root", str(parsed_root),
            "--corpus-root", str(corpus_root),
        ])
        out_eval = capsys.readouterr().out
        assert "Đánh giá trên 1/2 pub" in out_eval
        assert "2507.99999 (bibtex_missing_or_invalid+references_missing)" in out_eval
        assert "Recall    (cặp gold):        100.00% (1/1)" in out_eval

        # Trường hợp không có pub nào đánh giá được -> dừng sạch với thông báo rõ
        only_missing = tmp_path / "only_missing.jsonl"
        only_missing.write_text(
            json.dumps({"arxiv_id": "2507.99999", "citation_key": "k2", "groundtruth_arxiv_id": "1810.04805"}) + "\n",
            encoding="utf-8",
        )
        main([
            "--eval",
            "--gold", str(only_missing),
            "--parsed-root", str(parsed_root),
            "--corpus-root", str(corpus_root),
        ])
        out_none = capsys.readouterr().out
        assert "Không đánh giá được publication nào" in out_none
