"""Test validator_m2: cây đúng không báo lỗi; mỗi cây sai bị đúng phép kiểm dự kiến bắt."""

## Từ thư mục gốc repo, chạy test:
# bash
# python -m pytest tests/test_validator_m2.py -q
# Nếu muốn xem từng test: thêm -v. 
# Nếu chỉ chạy một ca: -k cycle (tên ca sai nằm trong BAD_CASES của fixtures_m2.py). Kết quả đúng là 34 passed.

## Khi có dữ liệu parse thật, chạy validator trên parsed/:
# python src/validator_m2.py --parsed parsed/ --corpus corpus/ --ids ids/mssv.txt

"""Test validator_m2: cây đúng không báo lỗi; mỗi cây sai bị đúng phép kiểm dự kiến bắt."""
import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import fixtures_m2 as fx  # noqa: E402
from validator_m2 import ValidatorM2, main, read_discovery, validate_publication  # noqa: E402


def run(d):
    return validate_publication(d["elements"], d["hierarchy"], d["arxiv_id"], n_versions=d["n_versions"])


def error_checks(issues):
    return {i.check for i in issues if i.severity == "error"}


@pytest.mark.parametrize("name", ["GOOD", "GOOD_REAL", "GOOD_EMPTY_VERSION"])
def test_good_trees_have_no_errors(name):
    issues = run(getattr(fx, name))
    assert error_checks(issues) == set(), [i.message for i in issues]


@pytest.mark.parametrize("name", list(fx.BAD_CASES))
def test_bad_tree_caught_by_expected_check(name):
    tree, expected = fx.BAD_CASES[name]
    issues = run(tree)
    assert error_checks(issues) == expected, [(i.check, i.message) for i in issues]


def test_shared_leaf_is_only_a_warning():
    issues = run(fx.GOOD)
    assert not error_checks(issues)


def test_empty_version_needs_marker():
    d = copy.deepcopy(fx.GOOD_EMPTY_VERSION)
    d["elements"] = [e for e in d["elements"] if e["element_id"] != f"{fx.PK}#root3"]
    assert error_checks(run(d)) == {"V6"}


def test_cli_on_disk(tmp_path):
    parsed = tmp_path / "parsed"
    pub = parsed / fx.PK
    pub.mkdir(parents=True)
    d = fx.GOOD_REAL
    (pub / "elements.jsonl").write_text("\n".join(json.dumps(r) for r in d["elements"]), encoding="utf-8")
    (pub / "hierarchy.jsonl").write_text("\n".join(json.dumps(r) for r in d["hierarchy"]), encoding="utf-8")
    out = tmp_path / "r.json"
    assert main(["--parsed", str(parsed), "--corpus", str(tmp_path / "nocorpus"), "--out", str(out)]) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["summary"]["passed"] is True
    assert data["checks"]["single_root"] == "pass"
    assert "dedup_ratio" in data
    assert "failures" in data
    # hỏng một dòng JSON -> lỗi, exit 1
    with open(pub / "hierarchy.jsonl", "a", encoding="utf-8") as fh:
        fh.write("\n{broken")
    assert main(["--parsed", str(parsed), "--corpus", str(tmp_path / "nocorpus"), "--out", str(out)]) == 1


def test_cli_ids_alias_and_limit(tmp_path):
    parsed = tmp_path / "parsed"
    pub = parsed / fx.PK
    pub.mkdir(parents=True)
    d = fx.GOOD_REAL
    (pub / "elements.jsonl").write_text("\n".join(json.dumps(r) for r in d["elements"]), encoding="utf-8")
    (pub / "hierarchy.jsonl").write_text("\n".join(json.dumps(r) for r in d["hierarchy"]), encoding="utf-8")
    ids_file = tmp_path / "ids.txt"
    ids_file.write_text(f"{fx.AID}\n9999.99999\n", encoding="utf-8")
    out = tmp_path / "r.json"
    # Dùng --ids và --limit 1 (chỉ xử lý fx.AID, bỏ qua 9999.99999)
    ret = main(["--parsed", str(parsed), "--corpus", str(tmp_path / "nocorpus"),
                "--ids", str(ids_file), "--limit", "1", "--out", str(out)])
    assert ret == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["n_publications"] == 1
    assert data["checks"]["single_root"] == "pass"
    assert data["checks"]["no_orphan"] == "pass"
    assert data["checks"]["no_cycle"] == "pass"
    assert data["checks"]["unique_element_id"] == "pass"
    assert data["checks"]["dedup_effective"] == "pass"
    assert data["checks"]["version_coverage"] == "pass"
    assert len(data["failures"]) == 0


# ---- V6 đối chiếu discovery.csv của M1 ------------------------------------------------------- #
def test_discovery_versions_match_is_ok():
    d = fx.GOOD
    issues = validate_publication(d["elements"], d["hierarchy"], d["arxiv_id"], discovery_versions={1, 2})
    assert error_checks(issues) == set(), [i.message for i in issues]


def test_discovery_version_missing_in_parsed_is_v6():
    # discovery.csv có v3 nhưng parsed chỉ có v1, v2 và không có bản ghi rỗng cho v3
    d = fx.GOOD
    issues = validate_publication(d["elements"], d["hierarchy"], d["arxiv_id"], discovery_versions={1, 2, 3})
    assert error_checks(issues) == {"V6"}


def test_cli_discovery_csv(tmp_path):
    parsed = tmp_path / "parsed"
    pub = parsed / fx.PK
    pub.mkdir(parents=True)
    d = fx.GOOD_REAL
    (pub / "elements.jsonl").write_text("\n".join(json.dumps(r) for r in d["elements"]), encoding="utf-8")
    (pub / "hierarchy.jsonl").write_text("\n".join(json.dumps(r) for r in d["hierarchy"]), encoding="utf-8")
    disc = tmp_path / "discovery.csv"
    disc.write_text(f"arxiv_id,version\n{fx.AID},1\n{fx.AID},2\n", encoding="utf-8")
    assert read_discovery(disc) == {fx.AID: {1, 2}}
    out = tmp_path / "r.json"
    args = ["--parsed", str(parsed), "--corpus", str(tmp_path / "nocorpus"), "--out", str(out)]
    assert main(args + ["--discovery", str(disc)]) == 0
    # discovery.csv thêm v3 mà parsed không có -> V6 fail, exit 1
    disc.write_text(f"arxiv_id,version\n{fx.AID},1\n{fx.AID},2\n{fx.AID},3\n", encoding="utf-8")
    assert main(args + ["--discovery", str(disc)]) == 1
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["checks"]["version_coverage"] == "fail"