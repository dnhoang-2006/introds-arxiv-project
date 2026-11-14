from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

SRC_DIR = str(Path(__file__).resolve().parent.parent / "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

try:
    from parser.bib_dedup import (
        _are_authors_compatible,
        _clean_author_name,
        _clean_year,
        _first_author_last_name,
        _is_same_author,
        _norm_doi,
        _norm_title,
        _norm_url,
        _split_authors_str,
        cluster_entries,
        entry_keys,
        merge_group,
        signature,
    )
except ImportError:
    from src.parser.bib_dedup import (  # type: ignore[no-redef]
        _are_authors_compatible,
        _clean_author_name,
        _clean_year,
        _first_author_last_name,
        _is_same_author,
        _norm_doi,
        _norm_title,
        _norm_url,
        _split_authors_str,
        cluster_entries,
        entry_keys,
        merge_group,
        signature,
    )


def _e(key: str = "k", title: str | None = None, authors: Any = None, **kwargs: Any) -> dict[str, Any]:
    """Helper ngắn gọn khởi tạo entry BibTeX cho kiểm thử."""
    entry: dict[str, Any] = {"citation_key": key}
    if title is not None:
        entry["title"] = title
    if authors is not None:
        entry["authors"] = authors
    entry.update(kwargs)
    return entry


# Kiểm thử signature()

def test_signature_priority():
    """Kiểm tra thứ tự ưu tiên: doi > arxiv_id > title/author > citation_key."""
    # 1. Có DOI: ưu tiên hàng đầu
    assert signature(_e("k1", "Attention Paper", ["A. Vaswani"], arxiv_id="1706.03762", doi="10.5555/3295222")) == "doi:10.5555/3295222"
    # 2. Không có DOI, có arXiv ID
    assert signature(_e("k2", "BERT Paper", ["J. Devlin"], arxiv_id="1810.04805")) == "arxiv:1810.04805"
    # 3. Không DOI, không arXiv ID: dùng tiêu đề + họ tác giả đầu
    assert signature(_e("k3", "Deep Learning Book", ["Goodfellow, Ian", "Bengio, Yoshua"])) == "title:deep learning book/goodfellow"
    # 4. Có URL (cho tài liệu web / mã nguồn / dataset)
    assert signature(_e("k_url", url="https://github.com/google/jax")) == "url:github.com/google/jax"
    # 5. Chỉ có tiêu đề, không có tác giả: kết hợp key + tiêu đề
    assert signature(_e("k4", "Open Source Codebase")) == "key:k4/open source codebase"
    # 6. Không có gì ngoài citation_key
    assert signature(_e("k5")) == "key:k5"


def test_signature_3_versions_example():
    """Test bắt buộc của đề (mục 5 / lịch 12/11): nhận ra v1 và v3 cùng tài liệu."""
    v1 = _e("vaswani2017", "Attention Is All You Need", "Vaswani, A.", year=2017)
    v2 = _e("vit_transformer", "Attention is all you need", "A. Vaswani", doi="10.5555/3295222")
    v3 = _e("vit_transformer", "Attention Is All You Need", "Vaswani, A.")
    assert signature(v1) == signature(v3) == "title:attention is all you need/vaswani"
    assert signature(v2) == "doi:10.5555/3295222"


def test_signature_multi_author_comma_separated():
    """Kiểm tra đồng nhất chữ ký giữa tác giả đơn và chuỗi nhiều tác giả nối bằng dấu phẩy."""
    e_single = _e("k1", "Attention Is All You Need", "A. Vaswani")
    e_multi_comma = _e("k2", "Attention Is All You Need", "A. Vaswani, N. Shazeer")
    e_last_first = _e("k3", "Attention is all you need", "Vaswani, A., Shazeer, N.")

    assert signature(e_single) == signature(e_multi_comma) == signature(e_last_first) == "title:attention is all you need/vaswani"
    groups = cluster_entries([e_single, e_multi_comma, e_last_first])
    assert len(groups) == 1
    assert len(groups[0]) == 3


def test_signature_author_format_variations_smith():
    """Kiểm tra đồng nhất họ tác giả giữa 'Smith J., Jones P.' và 'Smith, John, Jones P.'."""
    e_last_initial = _e("smith2020a", "Quantum Computing", "Smith J., Jones P.")
    e_last_first_full = _e("smith2020b", "Quantum Computing", "Smith, John, Jones P.")
    e_initial_last = _e("smith2020c", "Quantum Computing", "J. Smith, P. Jones")

    assert signature(e_last_initial) == signature(e_last_first_full) == signature(e_initial_last) == "title:quantum computing/smith"
    groups = cluster_entries([e_last_initial, e_last_first_full, e_initial_last])
    assert len(groups) == 1
    assert len(groups[0]) == 3


def test_cluster_entries_transitive():
    """Kiểm tra gom nhóm bắc cầu: v1 nối v3 qua tiêu đề, v2 nối v1 qua tiêu đề và nối v4 qua DOI."""
    v1 = _e("vaswani2017", "Attention Is All You Need", "Vaswani, A.", year=2017)
    v2 = _e("vit_transformer", "Attention is all you need", "A. Vaswani", doi="10.5555/3295222")
    v3 = _e("vit_transformer", "Attention Is All You Need", "Vaswani, A.")
    v4 = _e("v4_only_doi", doi="10.5555/3295222")
    unrelated = _e("he2016", "Deep Residual Learning for Image Recognition", "Kaiming He", doi="10.1109/CVPR.2016.90")

    groups = cluster_entries([v1, v2, v3, v4, unrelated])
    assert len(groups) == 2
    trans_group = next(g for g in groups if any(e["citation_key"] == "vaswani2017" for e in g))
    assert len(trans_group) == 4
    assert {e["citation_key"] for e in trans_group} == {"vaswani2017", "vit_transformer", "v4_only_doi"}
    other_group = next(g for g in groups if any(e["citation_key"] == "he2016" for e in g))
    assert len(other_group) == 1


def test_cluster_entries_different_authors_same_title_not_merged():
    """Hai bài báo trùng tiêu đề nhưng khác tác giả không được gộp chung."""
    p1 = _e("deep_goodfellow", "Deep Learning", ["Goodfellow, Ian"])
    p2 = _e("deep_lecun", "Deep Learning", ["LeCun, Yann"])
    assert len(cluster_entries([p1, p2])) == 2


def test_cluster_entries_different_citation_keys_no_authors_same_title_not_merged():
    """Hai tài liệu thiếu tác giả trùng tiêu đề nhưng khác citation_key không được gộp nhầm."""
    d1 = _e("user_guide_v1", "User Manual and Guidelines")
    d2 = _e("user_guide_v2", "User Manual and Guidelines")
    assert len(cluster_entries([d1, d2])) == 2


def test_cluster_entries_fallback_citation_key():
    """Các entry chỉ có citation_key giống nhau phải được gom nhóm cùng nhau."""
    groups = cluster_entries([_e("empty_cite_key", version=1), _e("empty_cite_key", version=2)])
    assert len(groups) == 1
    assert len(groups[0]) == 2


def test_cluster_entries_reused_key_different_titles_not_merged():
    """Hai tài liệu thiếu tác giả nhưng có tiêu đề khác nhau dùng chung citation_key không bị gộp nhầm."""
    e1 = _e("1", "Quantum Mechanics Handbook", version=1)
    e2 = _e("1", "Deep Learning Survey", version=2)
    assert len(cluster_entries([e1, e2])) == 2


def test_cluster_entries_different_urls_not_merged():
    """Tài liệu thiếu tác giả nhưng khác URL dùng chung citation_key không bị gộp nhầm."""
    e1 = _e("web_ref", url="https://github.com/google/jax")
    e2 = _e("web_ref", url="https://pytorch.org")
    assert len(cluster_entries([e1, e2])) == 2


def test_entry_keys_contains_signature():
    """Chữ ký chính của một entry luôn nằm trong tập entry_keys()."""
    samples = [
        _e("k1", "Some Paper", ["Doe, J."]),
        _e("k2", doi="10.1234/test"),
        _e("k3", arxiv_id="2310.12345"),
        _e("k4", url="https://github.com/test"),
        _e("k5", "Only Title"),
        _e("k6"),
    ]
    for s in samples:
        assert signature(s) in entry_keys(s)


# Kiểm thử merge_group()

def test_merge_group_union_fields():
    """Test bắt buộc (13/11): hợp nhất trường, kết quả phải có cả year (v1) và doi (v2)."""
    v1 = _e("vaswani2017", "Attention Is All You Need", "Vaswani, A.", year=2017)
    v2 = _e("vit_transformer", "Attention is all you need", "A. Vaswani", doi="10.5555/3295222")
    v3 = _e("vit_transformer", "Attention Is All You Need", "Vaswani, A.")

    merged, rename = merge_group([v1, v2, v3])
    assert merged["citation_key"] == "vaswani2017"
    assert merged["year"] == 2017
    assert merged["doi"] == "10.5555/3295222"
    assert merged["title"] == "Attention Is All You Need"
    assert merged["authors"] in ("Vaswani, A.", ["Vaswani, A."])
    assert rename["vit_transformer"] == "vaswani2017"
    assert rename["vaswani2017"] == "vaswani2017"


def test_merge_group_deterministic_key_selection():
    """Kiểm tra quy tắc chọn citation key chuẩn: version nhỏ -> key ngắn -> chữ cái."""
    # 1. Version nhỏ nhất thắng
    m1, _ = merge_group([_e("short", version=2), _e("transformer_very_long_key", version=1)])
    assert m1["citation_key"] == "transformer_very_long_key"

    # 2. Cùng version: key ngắn hơn thắng
    m2, _ = merge_group([_e("longer_key_name", version=1), _e("short_key", version=1)])
    assert m2["citation_key"] == "short_key"

    # 3. Cùng version và cùng độ dài: thứ tự chữ cái thắng
    m3, _ = merge_group([_e("key_b", version=1), _e("key_a", version=1)])
    assert m3["citation_key"] == "key_a"


def test_merge_group_author_and_entry_type_priority():
    """Kiểm tra ưu tiên authors list[str] và entry_type cụ thể hơn 'misc'."""
    e_misc = _e("ref1", "Title", "A. Vaswani", entry_type="misc")
    e_article = _e("ref1_v2", authors=["Vaswani, Ashish", "Shazeer, Noam"], entry_type="article", journal="NeurIPS")

    merged, _ = merge_group([e_misc, e_article])
    assert merged["entry_type"] == "article"
    assert merged["authors"] == ["Vaswani, Ashish", "Shazeer, Noam"]
    assert merged["journal"] == "NeurIPS"


def test_merge_group_edge_cases():
    """Kiểm tra các ca biên: danh sách rỗng, 1 phần tử."""
    assert merge_group([]) == ({}, {})
    single = _e("only_one", "Single Paper", year=2020)
    merged, rename = merge_group([single])
    assert merged["citation_key"] == "only_one"
    assert merged["year"] == 2020
    assert rename == {"only_one": "only_one"}


def test_merge_group_order_independence_same_version_and_key():
    """Kiểm tra tính tất định: cùng version và citation_key (.bib vs \\bibitem) không phụ thuộc thứ tự input."""
    e_bib = _e("vaswani2017", "Attention Is All You Need", ["Vaswani, Ashish", "Shazeer, Noam"], version=1, year=2017, entry_type="article")
    e_bibitem = _e(
        "vaswani2017", "Attention is all you need", "A. Vaswani",
        version=1, year=2018, raw="\\bibitem{vaswani2017} A. Vaswani. Attention is all you need. 2018.", entry_type="misc",
    )

    m1, r1 = merge_group([e_bib, e_bibitem])
    m2, r2 = merge_group([e_bibitem, e_bib])
    assert m1 == m2
    assert r1 == r2
    assert m1["year"] == 2017
    assert m1["authors"] == ["Vaswani, Ashish", "Shazeer, Noam"]
    assert m1["entry_type"] == "article"


@pytest.mark.parametrize("raw_year,expected", [
    (1800, 1800),
    ("1800", 1800),
    ("1763", 1763),
    ("2019a", 2019),
    ("May 2021", 2021),
    ("invalid", None),
])
def test_merge_group_clean_year_formats(raw_year, expected):
    """Kiểm tra trích xuất năm an toàn từ nhiều định dạng khác nhau (bao gồm năm lịch sử < 1900)."""
    merged, _ = merge_group([_e("k", year=raw_year, version=1)])
    assert merged["year"] == expected


def test_merge_group_entry_type_tie_breaker_deterministic():
    """Hai entry cùng version/key và các trường nhưng khác entry_type không phụ thuộc thứ tự input."""
    e_art = _e("k_same", "Same Title", ["Same Author"], version=1, entry_type="article")
    e_book = _e("k_same", "Same Title", ["Same Author"], version=1, entry_type="book")

    m1, r1 = merge_group([e_book, e_art])
    m2, r2 = merge_group([e_art, e_book])
    assert m1 == m2
    assert r1 == r2
    assert m1["entry_type"] == "article"


# Kiểm thử các ca biên và gom nhóm nâng cao

def test_cluster_entries_different_dois_same_url_not_merged():
    """Hai entry có DOI khác nhau nhưng cùng URL không được gộp vào cùng nhóm."""
    url = "https://ieeexplore.ieee.org/document/123456"
    e1 = _e("paper1", "Computer Vision Paper 1", doi="10.1109/CVPR.2020.001", url=url)
    e2 = _e("paper2", "Computer Vision Paper 2", doi="10.1109/CVPR.2020.002", url=url)
    assert len(cluster_entries([e1, e2])) == 2


def test_cluster_entries_different_dois_same_title_not_merged():
    """Hai entry có DOI khác nhau dù có cùng tiêu đề và tác giả không được gộp chung."""
    e1 = _e("p1", "Quantum Computing Basics", ["Feynman, R."], doi="10.1000/182")
    e2 = _e("p2", "Quantum Computing Basics", ["Feynman, R."], doi="10.1000/183")
    assert len(cluster_entries([e1, e2])) == 2


def test_cluster_entries_different_arxiv_ids_not_merged():
    """Hai entry có arXiv ID khác nhau không được gộp chung."""
    e1 = _e("ar1", arxiv_id="2101.00001", url="https://arxiv.org/abs/2101.00001")
    e2 = _e("ar2", arxiv_id="2101.00002", url="https://arxiv.org/abs/2101.00001")
    assert len(cluster_entries([e1, e2])) == 2


def test_merge_group_authors_union_no_loss():
    """Gộp tác giả không được làm mất tên khi một bên có ['A', 'B'] và một bên có ['A', 'C']."""
    e1 = _e("k1", version=1, authors=["Alice Smith", "Bob Jones"])
    e2 = _e("k2", version=2, authors=["Alice Smith", "Charlie Brown"])
    merged, _ = merge_group([e1, e2])
    assert merged["authors"] == ["Alice Smith", "Bob Jones", "Charlie Brown"]


def test_merge_group_authors_upgrade_initial_to_full_name():
    """Nâng cấp tên tác giả viết tắt lên tên đầy đủ khi hợp nhất."""
    e1 = _e("vaswani_v1", version=1, authors=["A. Vaswani", "N. Shazeer"])
    e2 = _e("vaswani_v2", version=2, authors=["Ashish Vaswani", "Noam Shazeer"])
    merged, _ = merge_group([e1, e2])
    assert merged["authors"] == ["Ashish Vaswani", "Noam Shazeer"]


def test_merge_group_authors_string_to_list_schema():
    """Chuỗi tác giả đầu vào phải được chuyển thành list[str] tuân thủ schema M2."""
    e1 = _e("k_raw", version=1, authors="Vaswani, Ashish and Shazeer, Noam and Parmar, Niki")
    merged, _ = merge_group([e1])
    assert isinstance(merged["authors"], list)
    assert merged["authors"] == ["Vaswani, Ashish", "Shazeer, Noam", "Parmar, Niki"]


@pytest.mark.parametrize("raw_url,expected", [
    ("https://example.org/PaperA", "example.org/PaperA"),
    ("https://example.org/papera", "example.org/papera"),
    ("https://ieeexplore.ieee.org/", None),
    ("http://springer.com/index.html", None),
    ("https://arxiv.org", None),
])
def test_norm_url_case_sensitive_path_and_generic_filtering(raw_url, expected):
    """URL path phân biệt hoa thường và URL trang chủ không được dùng làm khoá định danh."""
    assert _norm_url(raw_url) == expected


@pytest.mark.parametrize("raw_doi,expected", [
    ("doi:10.1234/abc", "10.1234/abc"),
    ("10.1234/abc", "10.1234/abc"),
    ("https://doi.org/10.1234/abc", "10.1234/abc"),
    ("http://dx.doi.org/10.1234/abc", "10.1234/abc"),
])
def test_norm_doi_doi_prefix_equivalence(raw_doi, expected):
    """Tiền tố doi: và URL DOI đều cho ra cùng chuỗi DOI chuẩn hoá."""
    assert _norm_doi(raw_doi) == expected


def test_cluster_entries_different_dois_shared_weak_key_order_independent():
    """Entry thiếu DOI không bị gán sai vào nhóm tùy thuộc vào thứ tự đầu vào."""
    e_a = _e("a", "Quantum Computing Survey", ["Smith, J."], doi="10.1000/182a")
    e_b = _e("b", "Quantum Computing Survey", ["Smith, J."], doi="10.1000/182b")
    e_c = _e("c", "Quantum Computing Survey", ["Smith, J."])

    groups_abc = cluster_entries([e_a, e_b, e_c])
    groups_bac = cluster_entries([e_b, e_a, e_c])
    assert len(groups_abc) == len(groups_bac) == 3

    keys_abc = sorted([sorted(list({e["citation_key"] for e in g})) for g in groups_abc])
    keys_bac = sorted([sorted(list({e["citation_key"] for e in g})) for g in groups_bac])
    assert keys_abc == keys_bac == [["a"], ["b"], ["c"]]


def test_merge_authors_distinct_people_same_last_name_and_initial():
    """Tác giả khác người nhưng cùng họ và chữ cái đầu (John Smith vs Jane Smith) không bị gộp nhầm."""
    m1, _ = merge_group([_e("k1", version=1, authors=["John Smith", "Jane Smith"])])
    assert m1["authors"] == ["John Smith", "Jane Smith"]

    m2, _ = merge_group([_e("k2", version=1, authors=["John Smith"]), _e("k2", version=2, authors=["Jane Smith"])])
    assert m2["authors"] == ["John Smith", "Jane Smith"]


@pytest.mark.parametrize("url,expected", [
    ("http://example.org:80/path", "example.org/path"),
    ("https://example.org:443/path", "example.org/path"),
    ("https://example.org:80/path", "example.org:80/path"),
    ("http://example.org:443/path", "example.org:443/path"),
])
def test_norm_url_protocol_specific_default_ports(url, expected):
    """Chuẩn hóa URL chỉ loại bỏ cổng mặc định theo đúng giao thức (http:80, https:443)."""
    assert _norm_url(url) == expected


def test_merge_group_title_selection_penalizes_all_caps():
    """Tiêu đề viết hoa toàn bộ (ALL CAPS) không được ưu tiên hơn Title Case hoặc Sentence Case."""
    e_all_caps = _e("k", "ATTENTION IS ALL YOU NEED", version=1)
    e_title_case = _e("k", "Attention Is All You Need", version=2)
    e_sentence_case = _e("k", "Attention is all you need", version=3)

    m1, _ = merge_group([e_all_caps, e_title_case])
    assert m1["title"] == "Attention Is All You Need"
    m2, _ = merge_group([e_title_case, e_all_caps])
    assert m2["title"] == "Attention Is All You Need"
    m3, _ = merge_group([e_all_caps, e_sentence_case])
    assert m3["title"] == "Attention is all you need"


def test_cluster_entries_same_title_distinct_authors_same_last_name_not_merged():
    """Hai tài liệu cùng tiêu đề nhưng khác tác giả (John Smith vs Jane Smith) không bị gộp nhầm."""
    p1 = _e("ml_john", "Machine Learning Fundamentals", ["John Smith"])
    p2 = _e("ml_jane", "Machine Learning Fundamentals", ["Jane Smith"])
    assert len(cluster_entries([p1, p2])) == 2


@pytest.mark.parametrize("name,expected", [
    ("Guido van Rossum", "vanrossum"),
    ("van Rossum, Guido", "vanrossum"),
    ("Jean-Luc de la Cruz", "delacruz"),
    ("de la Cruz, Jean-Luc", "delacruz"),
    ("John von Neumann", "vonneumann"),
    ("von Neumann, John", "vonneumann"),
])
def test_first_author_noble_particles_van_rossum_de_la_cruz(name, expected):
    """Họ kép có hạt (van Rossum, de la Cruz, von Neumann) cho cùng kết quả bất kể thứ tự viết."""
    assert _first_author_last_name(name) == expected


def test_split_authors_comma_only_pairs():
    """Chuỗi tác giả chỉ phân cách bằng dấu phẩy dạng Last, First, Last, First được tách chuẩn xác."""
    s = "Vaswani, Ashish, Shazeer, Noam, Parmar, Niki"
    assert _split_authors_str(s) == ["Vaswani, Ashish", "Shazeer, Noam", "Parmar, Niki"]
    merged, _ = merge_group([_e("k", version=1, authors="Vaswani, Ashish, Shazeer, Noam")])
    assert merged["authors"] == ["Vaswani, Ashish", "Shazeer, Noam"]


def test_cluster_entries_same_doi_different_author_names_merged():
    """Hai entry có cùng DOI luôn được gộp vào cùng một tài liệu dù tên tác giả ghi khác nhau."""
    doi = "10.1145/3308558.3313550"
    e1 = _e("k_doi_1", "BERT Paper", ["Devlin, Jacob"], doi=doi)
    e2 = _e("k_doi_2", "BERT: Pre-training of Deep Bidirectional Transformers", ["Google AI Team"], doi=doi)
    assert len(cluster_entries([e1, e2])) == 1


def test_cluster_entries_same_arxiv_different_author_names_merged():
    """Hai entry có cùng arXiv ID luôn được gộp vào cùng một tài liệu dù tên tác giả ghi khác nhau."""
    e1 = _e("k_ar_1", "BERT", ["J. Devlin"], arxiv_id="1810.04805")
    e2 = _e("k_ar_2", "BERT Model", ["Unknown Team"], arxiv_id="1810.04805")
    assert len(cluster_entries([e1, e2])) == 1


@pytest.mark.parametrize("variant", [
    "Gödel incompleteness theorem",
    r"G{\"o}del incompleteness theorem",
    r"G\"{o}del incompleteness theorem",
    r'G{"o}del incompleteness theorem',
])
def test_norm_title_tex_and_unicode_accents_equivalence(variant):
    """Chuẩn hóa tiêu đề xử lý đồng nhất giữa ký tự có dấu Unicode và lệnh tạo dấu trong TeX."""
    assert _norm_title(variant) == "godel incompleteness theorem"


@pytest.mark.parametrize("name,expected", [
    ("van Rossum, Guido Peter", "vanrossum"),
    ("Guido Peter van Rossum", "vanrossum"),
    ("de la Cruz, Jean Luc", "delacruz"),
    ("Jean Luc de la Cruz", "delacruz"),
])
def test_first_author_noble_particles_with_middle_name(name, expected):
    """Họ kép có hạt kèm middle name vẫn nhận diện chính xác họ bất kể thứ tự viết."""
    assert _first_author_last_name(name) == expected


def test_is_same_author_surname_only_not_merged_with_full_name():
    """Entry chỉ có họ không được tự ý coi là đồng nhất với tác giả có tên riêng đầy đủ."""
    assert _is_same_author("Smith", "John Smith") is False
    assert _is_same_author("John Smith", "Smith") is False
    assert _is_same_author("Smith", "Smith") is True


def test_cluster_entries_same_doi_different_arxiv_ids_merged():
    """Hai entry cùng DOI nhưng khác arXiv ID vẫn được gộp chung; merge_group giữ lại toàn bộ arXiv ID."""
    doi = "10.1145/3308558.3313550"
    e1 = _e("k1", "Paper Title", ["A. Author"], doi=doi, arxiv_id="1810.04805")
    e2 = _e("k2", "Paper Title", ["A. Author"], doi=doi, arxiv_id="1810.04806")
    groups = cluster_entries([e1, e2])
    assert len(groups) == 1
    merged, _ = merge_group(groups[0])
    assert merged["arxiv_id"] == "1810.04805, 1810.04806"

    # Trùng lặp sau khi chuẩn hóa (ví dụ "arXiv:1810.04805" và "1810.04805") được khử trùng lặp an toàn
    e3 = _e("k3", "Paper Title", ["A. Author"], doi=doi, arxiv_id="arXiv:1810.04805")
    merged_dedup, _ = merge_group([e1, e3])
    assert merged_dedup["arxiv_id"] == "1810.04805"


@pytest.mark.parametrize("t_uni,t_tex,expected", [
    ("Søren Kierkegaard", r"S\o ren Kierkegaard", "soren kierkegaard"),
    ("Kurt Gödel", r"Kurt G{\"o}del", "kurt godel"),
])
def test_norm_title_and_author_special_chars_soren_and_godel(t_uni, t_tex, expected):
    """Chuẩn hóa ký tự đặc biệt tiếng Bắc Âu/Đức (ø, ö) đồng nhất giữa Unicode và TeX macro."""
    assert _norm_title(t_uni) == _norm_title(t_tex) == expected


def test_entry_keys_links_rich_metadata_with_key_only_entry():
    """entry_keys() sinh khóa phụ dựa trên key+title để entry chỉ có key nối được với metadata đầy đủ."""
    e_rich = _e("k_shared", "Quantum Computing", ["John Smith"], doi="10.1000/182", version=1)
    e_sparse = _e("k_shared", version=2)
    assert len(cluster_entries([e_rich, e_sparse])) == 1


def test_signature_same_title_same_surname_collision_doc():
    """Ghi nhận giới hạn thiết kế: signature() cố ý dùng tiêu đề + họ tác giả đầu khi thiếu DOI/arXiv."""
    p_john = _e("j1", "Advanced Quantum Computing", ["John Smith"])
    p_jane = _e("j2", "Advanced Quantum Computing", ["Jane Smith"])
    assert signature(p_john) == signature(p_jane) == "title:advanced quantum computing/smith"
    assert len(cluster_entries([p_john, p_jane])) == 2


def test_cluster_entries_order_independence_shared_doi_distinct_authors_and_third_entry():
    """Gom nhóm độc lập thứ tự khi 2 entry cùng DOI khác tên tác giả và entry thứ ba không có DOI."""
    doi = "10.1145/3308558.3313550"
    title = "BERT: Pre-training of Deep Bidirectional Transformers"
    e_a = _e("a", title, ["Devlin, Jacob"], doi=doi)
    e_b = _e("b", title, ["Google AI Language Team"], doi=doi)
    e_c = _e("c", title, ["Google AI Language Team"])

    groups_abc = cluster_entries([e_a, e_b, e_c])
    groups_bac = cluster_entries([e_b, e_a, e_c])
    assert len(groups_abc) == len(groups_bac) == 1
    assert len(groups_abc[0]) == 3


def test_cluster_entries_same_title_and_author_different_urls_merged():
    """Khác biệt URL không được phép phủ quyết (veto) khi tiêu đề và tác giả đã khớp hoàn toàn."""
    title = "Attention Is All You Need"
    authors = ["Ashish Vaswani", "Noam Shazeer"]
    e1 = _e("vaswani_arxiv", title, authors, url="https://arxiv.org/abs/1706.03762")
    e2 = _e("vaswani_neurips", title, authors, url="https://proceedings.neurips.cc/paper/7181-attention")
    groups = cluster_entries([e1, e2])
    assert len(groups) == 1


def test_merge_group_preserves_unicode_accents_in_authors():
    """merge_group() bảo tồn ký tự có dấu Unicode và quy đổi các macro TeX sang Unicode NFC trong authors."""
    e_tex = _e("k_tex", authors=[r"Kurt G{\"o}del", r"S\o ren Kierkegaard", r"Poincar{\'e}", r"Jan {\L}ukasiewicz", r"Paul Erd{\H o}s"], version=1)
    e_uni = _e("k_uni", authors=["Kurt Gödel", "Søren Kierkegaard", "Poincaré", "Jan Łukasiewicz", "Paul Erdős"], version=2)
    merged, _ = merge_group([e_tex, e_uni])
    assert merged["authors"] == ["Kurt Gödel", "Søren Kierkegaard", "Poincaré", "Jan Łukasiewicz", "Paul Erdős"]


def test_merge_authors_preserves_initial_and_full_name_distinct_coauthors():
    """Tên viết tắt không làm nuốt hoặc mất một đồng tác giả khác trong cùng danh sách hoặc giữa các version."""
    m1, _ = merge_group([_e("c1", authors=["J. Smith", "Jane Smith"], version=1)])
    assert m1["authors"] == ["J. Smith", "Jane Smith"]

    m2, _ = merge_group([_e("c1", authors=["J. Smith", "Jane Smith"], version=1), _e("c2", authors=["Jane Smith"], version=2)])
    assert m2["authors"] == ["J. Smith", "Jane Smith"]

    m3, _ = merge_group([_e("c1", authors=["J. Smith", "Jane Smith"], version=1), _e("c3", authors=["John Smith", "Jane Smith"], version=2)])
    assert m3["authors"] == ["John Smith", "Jane Smith"]


@pytest.mark.parametrize("n1,n2,compatible,same", [
    ("J. Smith", "Jane Smith", True, False),
    ("J. Smith", "John Smith", True, False),
    ("John Smith", "Jane Smith", False, False),
    ("John Smith", "John Smith", True, True),
    ("J. Smith", "J. Smith", True, True),
])
def test_is_same_author_and_are_authors_compatible_distinction(n1, n2, compatible, same):
    """Phân biệt rõ ràng giữa tính tương thích (compatible) và tính đồng nhất nghiêm ngặt (same author)."""
    assert _are_authors_compatible(n1, n2) is compatible
    assert _is_same_author(n1, n2) is same


def test_cluster_entries_single_initial_ambiguous_not_merged():
    """Hai tài liệu cùng tiêu đề với tác giả viết tắt đơn lẻ 'J. Smith' và 'Jane Smith' không được gộp."""
    e1 = _e("k_j", "Quantum Computing Advances", ["J. Smith"])
    e2 = _e("k_jane", "Quantum Computing Advances", ["Jane Smith"])
    assert len(cluster_entries([e1, e2])) == 2


def test_cluster_entries_ambiguous_coauthors_single_initial_not_merged():
    """Đồng tác giả cũng chỉ có viết tắt đơn lẻ ('A. Brown' vs 'Alice Brown') không đủ làm bằng chứng khẳng định."""
    e1 = _e("k1", "Quantum Computing Advances", ["J. Smith", "A. Brown"])
    e2 = _e("k2", "Quantum Computing Advances", ["Jane Smith", "Alice Brown"])
    assert len(cluster_entries([e1, e2])) == 2


def test_cluster_entries_ambiguous_first_author_with_distinct_coauthor_merged():
    """Khi tác giả đầu viết tắt đơn lẻ nhưng đồng tác giả có tên đầy đủ hoặc viết tắt kép, gộp nhóm chính xác."""
    # 1. Đồng tác giả có tên riêng đầy đủ giống nhau hoàn toàn
    e1 = _e("k1", "Quantum Computing Advances", ["J. Smith", "Alice Brown"])
    e2 = _e("k2", "Quantum Computing Advances", ["Jane Smith", "Alice Brown"])
    groups = cluster_entries([e1, e2])
    assert len(groups) == 1
    assert len(groups[0]) == 2

    # 2. Đồng tác giả có viết tắt kép khớp nhau (A.B. Brown vs Alice Beatrice Brown)
    e3 = _e("k3", "Complex Systems Dynamics", ["J. Smith", "A.B. Brown"])
    e4 = _e("k4", "Complex Systems Dynamics", ["Jane Smith", "Alice Beatrice Brown"])
    groups2 = cluster_entries([e3, e4])
    assert len(groups2) == 1
    assert len(groups2[0]) == 2


def test_cluster_entries_compound_initials_merged():
    """Viết tắt kép 'J.P. Smith' và tên đầy đủ 'John Paul Smith' cùng tiêu đề được gom nhóm thành công."""
    e1 = _e("k_jp", "Complex Systems Dynamics", ["J.P. Smith"])
    e2 = _e("k_full", "Complex Systems Dynamics", ["John Paul Smith"])
    groups = cluster_entries([e1, e2])
    assert len(groups) == 1
    assert len(groups[0]) == 2


def test_clean_author_name_strips_tex_formatting_commands():
    """Lệnh định dạng TeX (\\textsc, \\textbf, \\textit) và dấu ngã ~ được làm sạch khỏi tên tác giả đầu ra."""
    assert _clean_author_name(r"\textsc{John Smith}") == "John Smith"
    assert _clean_author_name(r"\textbf{Jane Doe}") == "Jane Doe"
    assert _clean_author_name(r"{\it Albert} Einstein") == "Albert Einstein"
    assert _clean_author_name(r"J.~P.~Smith") == "J. P. Smith"
    assert _clean_author_name(r"Kurt G{\"o}del") == "Kurt Gödel"

    e = _e("tex_fmt", authors=[r"\textsc{John Smith}", r"J.~P.~Morgan", r"Kurt G{\"o}del"], version=1)
    merged, _ = merge_group([e])
    assert merged["authors"] == ["John Smith", "J. P. Morgan", "Kurt Gödel"]


def test_cluster_entries_three_entries_same_title_disambiguated():
    """Ba entry cùng tiêu đề: [John Smith, Jane Smith, John Smith] gom chính xác thành 2 nhóm độc lập thứ tự."""
    e_john_1 = _e("j1", "Deep Learning Theory", ["John Smith"], version=1)
    e_jane = _e("jane", "Deep Learning Theory", ["Jane Smith"], version=2)
    e_john_2 = _e("j2", "Deep Learning Theory", ["John Smith"], version=3)

    for order in ([e_john_1, e_jane, e_john_2], [e_jane, e_john_1, e_john_2]):
        groups = cluster_entries(order)
        assert len(groups) == 2
        john_grp = next(g for g in groups if any(e["citation_key"] == "j1" for e in g))
        assert len(john_grp) == 2
        assert {e["citation_key"] for e in john_grp} == {"j1", "j2"}
