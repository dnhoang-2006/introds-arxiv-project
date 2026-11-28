"""Test cho scripts/pick_pubs.py — chọn publication gán tay bằng tiêu chí đo được."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
_spec = importlib.util.spec_from_file_location("pick_pubs", ROOT / "scripts" / "pick_pubs.py")
pick_pubs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pick_pubs)

import config  # noqa: E402


def _pub(root: Path, aid: str, entries: list[dict], refs: list[dict]) -> None:
    pk = config.pub_key(aid)
    cd = root / "corpus" / pk
    pd_ = root / "parsed" / pk
    cd.mkdir(parents=True, exist_ok=True)
    pd_.mkdir(parents=True, exist_ok=True)
    (cd / "paper_meta.json").write_text(json.dumps({
        "arxiv_id": aid, "title": f"Meta {aid}", "authors": [],
        "submission_date": None, "revised_dates": [], "venue": None,
    }), encoding="utf-8")
    (cd / "references.json").write_text(json.dumps({
        "arxiv_id": aid, "status": "ok", "n_total": len(refs),
        "n_with_arxiv": len(refs),
        "references": [{"arxiv_id": aid, "has_arxiv_id": True, **r} for r in refs],
    }), encoding="utf-8")
    (pd_ / "bibtex.jsonl").write_text(
        "\n".join(json.dumps({"arxiv_id": aid, **e}) for e in entries),
        encoding="utf-8")


def _simple(root: Path, aid: str, n: int, *, titles_match: bool = True,
            url_ids: int = 0) -> None:
    refs = [{"ref_arxiv_id": f"23{i:02d}.0{i:04d}", "ref_title": f"Deep study number {i}",
             "ref_authors": ["X Y"], "ref_year": 2023} for i in range(n)]
    entries = []
    for i in range(n):
        entries.append({
            "citation_key": f"k{i}",
            "title": f"Deep study number {i}" if titles_match else f"zzz unrelated {i} qqq",
            "authors": ["X Y"], "year": 2023, "doi": None, "journal": None,
            "url": f"https://arxiv.org/abs/23{i:02d}.0{i:04d}" if i < url_ids else None,
        })
    _pub(root, aid, entries, refs)


# --- hàm thuần -------------------------------------------------------------

def test_overlap_chia_cho_ben_nho_hon():
    assert pick_pubs.overlap({"a", "b"}, {"a", "b", "c", "d"}) == 1.0
    assert pick_pubs.overlap({"a", "b", "c", "d"}, {"a", "z"}) == 0.5
    assert pick_pubs.overlap(set(), {"a"}) == 0.0
    assert pick_pubs.overlap({"a"}, {"b"}) == 0.0


@pytest.mark.parametrize("field", ["url", "doi", "journal"])
def test_entry_ids_doc_duoc_tu_ba_truong(field):
    e = {field: "see https://arxiv.org/abs/2301.12345v2 for details"}
    assert pick_pubs._entry_ids(e) == {"2301.12345"}


def test_entry_ids_bo_qua_so_khong_phai_arxiv():
    assert pick_pubs._entry_ids({"doi": "10.1109/TPAMI.2019.1234567"}) == set()
    assert pick_pubs._entry_ids({"url": None, "doi": None, "journal": None}) == set()


def test_entry_ids_bat_dang_arxiv_cham_va_id_cu():
    assert pick_pubs._entry_ids({"journal": "arXiv:2301.12345"}) == {"2301.12345"}
    assert pick_pubs._entry_ids({"url": "arxiv.org/abs/hep-th/9901001"}) == {"hep-th/9901001"}


# --- score_pub -------------------------------------------------------------

def test_score_pub_dem_dung_ca_hai_tin_hieu(tmp_path):
    _simple(tmp_path, "2504.00001", 30, url_ids=7)
    r = pick_pubs.score_pub("2504.00001", parsed_root=tmp_path / "parsed",
                            corpus_root=tmp_path / "corpus")
    assert r["entry"] == 30 and r["ref"] == 30
    assert r["co_id"] == 7            # chỉ 7 entry có arXiv ID trong url
    assert r["co_title"] == 30        # nhưng tiêu đề thì khớp hết
    assert r["uoc_tinh"] == 30        # hợp của hai tập, không phải tổng


def test_score_pub_tieu_de_khong_khop_thi_chi_con_tin_hieu_id(tmp_path):
    _simple(tmp_path, "2504.00002", 20, titles_match=False, url_ids=6)
    r = pick_pubs.score_pub("2504.00002", parsed_root=tmp_path / "parsed",
                            corpus_root=tmp_path / "corpus")
    assert r["co_title"] == 0
    assert r["co_id"] == 6
    assert r["uoc_tinh"] == 6


def test_score_pub_tra_none_khi_thieu_du_lieu(tmp_path):
    _pub(tmp_path, "2504.00003", [], [{"ref_arxiv_id": "2301.1", "ref_title": "T"}])
    assert pick_pubs.score_pub("2504.00003", parsed_root=tmp_path / "parsed",
                               corpus_root=tmp_path / "corpus") is None


def test_score_pub_bo_reference_khong_co_arxiv_id(tmp_path):
    """Kho ứng viên chỉ gồm reference có arXiv ID — đúng như load_references."""
    aid = "2504.00004"
    pk = config.pub_key(aid)
    (tmp_path / "corpus" / pk).mkdir(parents=True)
    (tmp_path / "parsed" / pk).mkdir(parents=True)
    (tmp_path / "corpus" / pk / "paper_meta.json").write_text(
        json.dumps({"arxiv_id": aid, "title": "T", "authors": [],
                    "submission_date": None, "revised_dates": [], "venue": None}),
        encoding="utf-8")
    (tmp_path / "corpus" / pk / "references.json").write_text(json.dumps({
        "arxiv_id": aid, "status": "ok", "n_total": 2, "n_with_arxiv": 1,
        "references": [
            {"ref_arxiv_id": "2301.00001", "has_arxiv_id": True, "ref_title": "A"},
            {"ref_arxiv_id": None, "has_arxiv_id": False, "ref_title": "B"},
        ]}), encoding="utf-8")
    (tmp_path / "parsed" / pk / "bibtex.jsonl").write_text(
        json.dumps({"arxiv_id": aid, "citation_key": "k0", "title": "A"}) + "\n",
        encoding="utf-8")
    r = pick_pubs.score_pub(aid, parsed_root=tmp_path / "parsed",
                            corpus_root=tmp_path / "corpus")
    assert r["ref"] == 1


# --- lệnh rank / check -----------------------------------------------------

def _args(**kw):
    import argparse
    return argparse.Namespace(**kw)


def test_rank_loai_bai_duoi_nguong_va_sap_theo_so_entry(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(pick_pubs, "ROOT", tmp_path)        # không có labels/
    _simple(tmp_path, "2504.00010", 40)       # đạt
    _simple(tmp_path, "2504.00011", 30)       # đạt, rẻ hơn
    _simple(tmp_path, "2504.00012", 10)       # dưới ngưỡng uoc_tinh
    ids = tmp_path / "ids.txt"
    ids.write_text("2504.00010\n2504.00011\n2504.00012\n", encoding="utf-8")

    rc = pick_pubs.cmd_rank(_args(
        mssv="24120053", ids=ids, parsed_root=tmp_path / "parsed",
        corpus_root=tmp_path / "corpus", min_entry=25, max_entry=55, top=20))
    out = capsys.readouterr().out
    assert rc == 0
    assert "2504.00012" not in out                      # bị loại
    # rẻ trước: 30 entry đứng trên 40 entry
    assert out.index("2504.00011") < out.index("2504.00010")


def test_rank_bao_loi_khi_khong_bai_nao_dat(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(pick_pubs, "ROOT", tmp_path)
    _simple(tmp_path, "2504.00013", 8)
    ids = tmp_path / "ids.txt"
    ids.write_text("2504.00013\n", encoding="utf-8")
    rc = pick_pubs.cmd_rank(_args(
        mssv="24120053", ids=ids, parsed_root=tmp_path / "parsed",
        corpus_root=tmp_path / "corpus", min_entry=25, max_entry=55, top=20))
    assert rc == 1
    assert "Không bài nào đạt" in capsys.readouterr().out


def test_rank_bo_qua_bai_da_co_nhan(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(pick_pubs, "ROOT", tmp_path)
    _simple(tmp_path, "2504.00014", 30)
    _simple(tmp_path, "2504.00015", 30)
    d = tmp_path / "labels" / "manual"
    d.mkdir(parents=True)
    (d / "24120053.jsonl").write_text(json.dumps(
        {"arxiv_id": "2504.00014", "citation_key": "k0",
         "groundtruth_arxiv_id": None, "labeler": "24120053", "method": "manual"}
    ) + "\n", encoding="utf-8")
    ids = tmp_path / "ids.txt"
    ids.write_text("2504.00014\n2504.00015\n", encoding="utf-8")

    pick_pubs.cmd_rank(_args(
        mssv="24120053", ids=ids, parsed_root=tmp_path / "parsed",
        corpus_root=tmp_path / "corpus", min_entry=25, max_entry=55, top=20))
    out = capsys.readouterr().out
    assert "2504.00014" not in out
    assert "2504.00015" in out


def test_check_canh_bao_khi_chong_lan_reference_cao(tmp_path, capsys):
    """Hai bài trích gần hết cùng một đám reference = cùng lĩnh vực."""
    refs = [{"ref_arxiv_id": f"2301.{i:05d}", "ref_title": f"Shared work {i}",
             "ref_authors": ["A B"], "ref_year": 2023} for i in range(30)]
    ents = [{"citation_key": f"k{i}", "title": f"Shared work {i}", "authors": ["A B"],
             "year": 2023, "doi": None, "journal": None, "url": None} for i in range(30)]
    _pub(tmp_path, "2504.00020", ents, refs)
    _pub(tmp_path, "2504.00021", ents, refs)      # y hệt

    rc = pick_pubs.cmd_check(_args(
        mssv="24120053", pubs="2504.00020,2504.00021",
        parsed_root=tmp_path / "parsed", corpus_root=tmp_path / "corpus"))
    out = capsys.readouterr().out
    assert rc == 0
    assert "TRÙNG LĨNH VỰC" in out
    assert "100.0%" in out


def test_check_canh_bao_khi_bai_duoi_nguong_va_khi_khong_du_nam_bai(tmp_path, capsys):
    _simple(tmp_path, "2504.00030", 30)
    _simple(tmp_path, "2504.00031", 10)
    pick_pubs.cmd_check(_args(
        mssv="24120053", pubs="2504.00030,2504.00031",
        parsed_root=tmp_path / "parsed", corpus_root=tmp_path / "corpus"))
    out = capsys.readouterr().out
    assert "đúng 5 bài, đang có 2" in out
    warn = [l for l in out.splitlines() if l.startswith("CẢNH BÁO") and "dưới" in l]
    assert len(warn) == 1 and "2504.00031" in warn[0] and "2504.00030" not in warn[0]


def test_check_chi_bao_dat_khi_du_ca_ba_tieu_chi(tmp_path, capsys):
    for i in range(5):
        # reference khác nhau hoàn toàn giữa các bài -> chồng lấn 0%
        refs = [{"ref_arxiv_id": f"23{i}{j:04d}.00001", "ref_title": f"Field {i} work {j}",
                 "ref_authors": ["A B"], "ref_year": 2023} for j in range(30)]
        ents = [{"citation_key": f"k{j}", "title": f"Field {i} work {j}",
                 "authors": ["A B"], "year": 2023, "doi": None, "journal": None,
                 "url": None} for j in range(30)]
        _pub(tmp_path, f"2504.0004{i}", ents, refs)
    pubs = ",".join(f"2504.0004{i}" for i in range(5))

    rc = pick_pubs.cmd_check(_args(
        mssv="24120053", pubs=pubs, parsed_root=tmp_path / "parsed",
        corpus_root=tmp_path / "corpus"))
    out = capsys.readouterr().out
    assert rc == 0
    assert "Cả 3 tiêu chí đều đạt" in out
    assert "CẢNH BÁO" not in out
