"""
Tests for the A3 modules: oai_harvester, kaggle_loader, cross_validate. No network.
"""

from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
import requests
from lxml import etree
from sickle import oaiexceptions

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import cross_validate as cv
import kaggle_loader
import oai_harvester as oai

RECORD_XML = """<?xml version="1.0" encoding="UTF-8"?>
<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">
<{verb}>
<record><header>
  <identifier>oai:arXiv.org:2507.06659</identifier>
  <datestamp>2025-12-17</datestamp>
  <setSpec>physics:nlin:AO</setSpec>
</header><metadata>
<arXivRaw xmlns="http://arxiv.org/OAI/arXivRaw/">
  <id>2507.06659</id>
  <version version="v1"><date>Wed, 09 Jul 2025 08:44:35 GMT</date><size>589kb</size></version>
  <version version="v2"><date>Tue, 16 Dec 2025 06:43:51 GMT</date><size>706kb</size></version>
  <title>Café Spreading</title>
  <authors>Jung-Hoon Jung and Young-Ho Eom</authors>
  <journal-ref>Phys. Rev. E 112, 064308</journal-ref>
</arXivRaw></metadata></record>
{tail}
</{verb}></OAI-PMH>"""
DELETED_XML = """<record xmlns="http://www.openarchives.org/OAI/2.0/"><header status="deleted">
  <identifier>oai:arXiv.org:hep-th/9901001</identifier><datestamp>2025-01-01</datestamp>
</header></record>"""
TOKEN_ERROR_XML = """<?xml version="1.0"?><OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">
<error code="badResumptionToken">expired</error></OAI-PMH>"""


def make_response(body: str, status: int = 200) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response._content = body.encode("utf-8")
    response.headers["Content-Type"] = "text/xml"
    return response


class FakeSession:
    """Trả lần lượt các phản hồi cho trước; phần tử là Exception thì ném ra."""

    def __init__(self, replies: list) -> None:
        self.replies = list(replies)
        self.calls: list[dict] = []
        self.headers: dict[str, str] = {}

    def get(self, url: str, params: dict, timeout: float) -> requests.Response:
        self.calls.append(params)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    def close(self) -> None:
        pass


@pytest.fixture
def client(monkeypatch, tmp_path):
    """PoliteSickle không ngủ, không gọi mạng, ghi log vào tmp_path."""
    monkeypatch.setattr(oai, "REQUEST_LOG", tmp_path / "requests.csv")
    monkeypatch.setattr(oai, "TOKEN_LOG", tmp_path / "tokens.jsonl")
    monkeypatch.setattr(oai, "TOKEN_CHECK_LOG", tmp_path / "checks.csv")
    monkeypatch.setattr(oai, "CHECKPOINT", tmp_path / "checkpoint.json")
    monkeypatch.setattr(oai.time, "sleep", lambda _: None)
    instance = oai.PoliteSickle(max_retries=2)
    instance._limiter.wait = lambda: None
    return instance


def page(token: str = "") -> str:
    tail = f"<resumptionToken>{token}</resumptionToken>" if token else ""
    return RECORD_XML.format(verb="ListRecords", tail=tail)


# --- oai_harvester ----------------------------------------------------
def test_non_ascii_decoded_as_utf8_despite_text_xml(client):
    """text/xml không khai charset: requests mặc định dùng Latin-1 làm hỏng title."""
    client._session = FakeSession([make_response(page())])
    response = client.harvest(verb="ListRecords")
    record = oai.parse_record(response.xml.find(f".//{oai.OAI_NS}record"), "ListRecords")
    assert record["title"] == "Café Spreading"


def test_parse_record_keeps_every_version():
    root = etree.fromstring(page().encode("utf-8"))
    record = oai.parse_record(root.find(f".//{oai.OAI_NS}record"), "GetRecord")
    assert record["id"] == "2507.06659"
    assert record["datestamp"] == "2025-12-17"
    assert [v["version"] for v in record["versions"]] == ["v1", "v2"]
    assert record["versions"][1]["size"] == "706kb"
    assert record["journal_ref"] == "Phys. Rev. E 112, 064308"


def test_parse_deleted_record_has_only_header():
    record = oai.parse_record(etree.fromstring(DELETED_XML), "ListRecords")
    assert record["id"] == "hep-th/9901001"
    assert record["deleted"] is True
    assert "title" not in record


def test_retry_on_503_with_retry_after_zero_then_success(client):
    busy = make_response("busy", 503)
    busy.headers["Retry-After"] = "0"
    client._session = FakeSession([busy, requests.Timeout(), make_response(page())])
    assert client.harvest(verb="ListRecords").xml is not None
    assert len(client._session.calls) == 3


def test_gives_up_after_retries_and_logs_each_attempt(client):
    client._session = FakeSession([make_response("x", 503) for _ in range(3)])
    with pytest.raises(oai.OAIUnavailable) as caught:
        client.harvest(verb="ListRecords")
    assert caught.value.error_type == "http_503"
    assert len(oai.REQUEST_LOG.read_text(encoding="utf-8").splitlines()) == 4  # header + 3


def test_no_retry_on_400(client):
    client._session = FakeSession([make_response("x", 400)])
    with pytest.raises(oai.OAIUnavailable):
        client.harvest(verb="ListRecords")
    assert len(client._session.calls) == 1


def test_window_follows_token_and_stops_at_max_pages(client, tmp_path):
    client._session = FakeSession([make_response(page("t1")), make_response(page("t2"))])
    out = tmp_path / "records.jsonl"
    params = oai.window_params("2025-07-10", "2025-07-10", None)
    summary = oai.harvest_window(client, params, max_pages=2, out_path=out)
    assert summary["pages"] == 2 and summary["complete"] is False
    assert client._session.calls[1] == {"verb": "ListRecords", "resumptionToken": "t1"}
    assert json.loads(oai.CHECKPOINT.read_text(encoding="utf-8"))["token"] == "t2"


def test_expired_token_restarts_window(client, tmp_path, monkeypatch):
    out = tmp_path / "records.jsonl"
    params = oai.window_params("2025-07-10", "2025-07-10", None)
    oai.CHECKPOINT.write_text(json.dumps({
        "query": params, "token": "old", "issued_at_utc": "2025-07-09T10:00:00+00:00",
    }), encoding="utf-8")
    monkeypatch.setattr(oai, "RECORDS_PATH", out)
    original = oai.harvest_window
    monkeypatch.setattr(oai, "harvest_window",
                        lambda c, p, m, start_token=None: original(c, p, m, start_token, out))
    client._session = FakeSession([make_response(TOKEN_ERROR_XML), make_response(page())])

    summary = oai.resume_or_restart(client, params, max_pages=5)

    assert client._session.calls[0] == {"verb": "ListRecords", "resumptionToken": "old"}
    assert client._session.calls[1]["from"] == "2025-07-10"
    assert summary["records"] == 1
    check_log = oai.TOKEN_CHECK_LOG.read_text(encoding="utf-8")
    assert "badResumptionToken" in check_log
    assert "True" in check_log  # crossed_utc_midnight
    assert not oai.CHECKPOINT.exists()


def test_error_codes_map_to_sickle_exceptions(client):
    client._session = FakeSession([make_response(TOKEN_ERROR_XML)])
    with pytest.raises(oaiexceptions.BadResumptionToken):
        oai.raise_oai_error(client.harvest(verb="ListRecords"))


def test_rejected_token_is_recorded_not_raised(client):
    client._session = FakeSession([make_response(TOKEN_ERROR_XML)])
    assert oai.try_token(client, "forged", "nope", None) == ""
    assert "BadResumptionToken" in oai.TOKEN_CHECK_LOG.read_text(encoding="utf-8")


@pytest.mark.parametrize("start,end", [("2025-07-01", "2025-07-08"), ("2025-07-10", "2025-07-09")])
def test_window_guard_rejects_wide_or_reversed(start, end):
    with pytest.raises(ValueError):
        oai.validate_window(start, end)


def test_sample_is_reproducible():
    ids = [str(i) for i in range(100)]
    assert oai.choose_sample(ids, 10, 42) == oai.choose_sample(ids, 10, 42)
    assert oai.choose_sample(ids, None, 42) == ids


# --- kaggle_loader ----------------------------------------------------
def snapshot_rows() -> list[dict]:
    base = {"authors": "A B", "authors_parsed": [["B", "A", ""]], "journal-ref": None,
            "doi": None, "categories": "cs.AI", "update_date": "2025-07-10",
            "abstract": "x", "versions": [{"version": "v1", "created": "Wed, 09 Jul 2025 08:44:35 GMT"}]}
    return [
        {**base, "id": "2507.10000", "title": "Trailing zero"},
        {**base, "id": "2507.1", "title": "Must not match 2507.10000"},
        {**base, "id": "hep-th/9901001", "title": "Old style"},
        {**base, "id": "0704.0001", "title": "Leading zero"},
        {**base, "id": "2507.99999", "title": "Not assigned"},
    ]


@pytest.mark.parametrize("zipped", [False, True])
def test_loader_keeps_ids_as_strings_and_filters(tmp_path, zipped):
    text = "\n".join(json.dumps(r) for r in snapshot_rows()) + "\n"
    path = tmp_path / "snapshot.json"
    path.write_text(text, encoding="utf-8")
    if zipped:
        archive = tmp_path / "snapshot.zip"
        with zipfile.ZipFile(archive, "w") as z:
            z.write(path, "snapshot.json")
        path = archive

    wanted = ["2507.10000v2", "hep-th/9901001", "0704.0001", "2507.77777"]
    records, n_rows = kaggle_loader.filter_snapshot(path, wanted, chunk_rows=2)

    assert n_rows == 5
    assert sorted(records["id"]) == ["0704.0001", "2507.10000", "hep-th/9901001"]
    assert "abstract" not in records.columns


# --- cross_validate ---------------------------------------------------
def api_meta(**overrides) -> dict:
    meta = {
        "arxiv_id": "2507.06659", "title": "A Title", "authors": ["Sébastien Pecqueur", "J. Doe"],
        "submission_date": "2025-07-09T08:44:35+00:00",
        "revised_dates": ["2025-12-16T06:43:51+00:00"],
        "venue": "Phys. Rev. E", "n_versions": 2, "revised_dates_complete": True,
    }
    return {**meta, **overrides}


def raw_record(**overrides) -> dict:
    record = {
        "title": "A Title", "authors": r"S\'ebastien Pecqueur and J. Doe",
        "journal_ref": "Phys. Rev. E",
        "versions": [{"date": "Wed, 09 Jul 2025 08:44:35 GMT"},
                     {"date": "Tue, 16 Dec 2025 06:43:51 GMT"}],
    }
    return {**record, **overrides}


def test_latex_authors_match_unicode_only_after_normalizing():
    left, right = cv.from_api(api_meta()), cv.from_oai(raw_record())
    assert cv.compare_field("authors", left, right) == cv.IDENTICAL  # delatex đã đưa về Unicode
    upper = cv.from_oai(raw_record(authors=r"S\'EBASTIEN PECQUEUR and J. Doe"))
    assert cv.compare_field("authors", left, upper) == cv.NORMALIZED


def test_dates_compared_across_formats():
    left, right = cv.from_api(api_meta()), cv.from_oai(raw_record())
    assert cv.compare_field("submission_date", left, right) == cv.IDENTICAL
    assert cv.compare_field("latest_date", left, right) == cv.IDENTICAL
    assert cv.compare_field("n_versions", left, right) == cv.IDENTICAL


def test_single_version_latest_date_is_submission():
    api = cv.from_api(api_meta(revised_dates=[], n_versions=1))
    assert api.latest_date == api.submission_date


def test_venue_only_one_side_and_null_both():
    with_venue = cv.from_api(api_meta())
    without = cv.from_oai(raw_record(journal_ref=None))
    assert cv.compare_field("venue", with_venue, without) == cv.ONLY_LEFT
    assert cv.compare_field("venue", without, with_venue) == cv.ONLY_RIGHT
    assert cv.compare_field("venue", without, without) == cv.BOTH_NULL


def test_tables_count_coverage_and_disagreements():
    good_api, good_oai = cv.from_api(api_meta()), cv.from_oai(raw_record())
    stale = cv.from_api(api_meta(n_versions=1))
    tables = {
        "API": {"a": good_api, "b": stale},
        "OAI": {"a": good_oai, "b": good_oai},
        "Kaggle": {"a": good_oai},
    }
    agreement, disagreements = cv.compare_sources(tables)
    versions = agreement[(agreement["pair"] == "API vs OAI") & (agreement["field"] == "n_versions")]
    assert versions.iloc[0]["n_compared"] == 2
    assert versions.iloc[0][cv.DIFFERENT] == 1
    assert disagreements.query("field == 'n_versions'").iloc[0]["arxiv_id"] == "b"

    three = cv.three_way(tables).set_index("field")
    assert three.loc["n_versions", "n_common"] == 1
    assert three.loc["n_versions", "all_three_identical"] == 1

    cover = cv.coverage(["a", "b", "c"], tables).set_index("source")
    assert cover.loc["Kaggle", "n_present"] == 1
    assert cover.loc["Kaggle", "n_missing"] == 2


def test_recheck_separates_stale_snapshot_from_real_difference(monkeypatch):
    fresh = {
        "stale": SimpleNamespace(n_versions=3, venue=None),
        "real": SimpleNamespace(n_versions=1, venue=None),
    }
    monkeypatch.setattr(cv.discovery, "build_client", lambda: None)
    monkeypatch.setattr(cv.discovery, "resolve_batch", lambda ids, client: fresh)
    disagreements = pd.DataFrame([
        {"arxiv_id": "stale", "field": "n_versions", "left_source": "API",
         "right_source": "Kaggle", "outcome": cv.DIFFERENT, "left_value": "2", "right_value": "3"},
        {"arxiv_id": "real", "field": "venue", "left_source": "API",
         "right_source": "Kaggle", "outcome": cv.ONLY_RIGHT, "left_value": "", "right_value": "A&A"},
        {"arxiv_id": "other", "field": "title", "left_source": "API",
         "right_source": "Kaggle", "outcome": cv.DIFFERENT, "left_value": "a", "right_value": "b"},
    ])
    result = cv.recheck_api(disagreements).set_index("arxiv_id")
    assert result.loc["stale", "verdict"] == "stale_snapshot"
    assert result.loc["real", "verdict"] == "still_differs"
    assert "other" not in result.index
