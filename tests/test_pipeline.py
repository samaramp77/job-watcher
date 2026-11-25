import gzip
import json
from datetime import date, datetime, timezone

import pipeline


GREENHOUSE = {
    "name": "greenhouse-demo",
    "employer": "Demo Co",
    "ats": "greenhouse",
    "board": "demo",
    "url": "https://example.test/greenhouse",
}
LEVER = {
    "name": "lever-demo",
    "employer": "Lever Demo",
    "ats": "lever",
    "board": "demo",
    "url": "https://example.test/lever",
}


def write_raw(raw_root, day, source, payload):
    path = raw_root / day / f"{source['name']}.json.gz"
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wb") as handle:
        handle.write(json.dumps(payload).encode())


def greenhouse_job(job_id, title="Senior Financial Analyst", location="Chicago, IL"):
    return {
        "id": job_id,
        "title": title,
        "location": {"name": location},
        "departments": [{"name": "Data"}],
        "first_published": "2026-01-01T10:00:00Z",
        "absolute_url": f"https://example.test/jobs/{job_id}",
    }


def test_greenhouse_conversion_to_common_columns():
    rows = pipeline.normalize_greenhouse(
        {"jobs": [greenhouse_job(17, "Senior Financial Analyst")]}, GREENHOUSE
    )
    assert rows == [
        {
            "posting_id": "greenhouse-demo:17",
            "source": "greenhouse-demo",
            "source_id": "17",
            "employer": "Demo Co",
            "title": "Senior Financial Analyst",
            "location": "Chicago, IL",
            "department": "Data",
            "posted_date": "2026-01-01",
            "url": "https://example.test/jobs/17",
            "in_role": True,
        }
    ]


def test_lever_conversion_to_common_columns():
    rows = pipeline.normalize_lever(
        [
            {
                "id": "abc",
                "text": "Product Designer",
                "categories": {"location": "Remote", "team": "Design"},
                "createdAt": 1767261600000,
                "hostedUrl": "https://example.test/lever/abc",
            }
        ],
        LEVER,
    )
    assert rows[0]["posting_id"] == "lever-demo:abc"
    assert rows[0]["employer"] == "Lever Demo"
    assert rows[0]["location"] == "Remote"
    assert rows[0]["department"] == "Design"
    assert rows[0]["posted_date"] == "2026-01-01"
    assert rows[0]["in_role"] is False


def test_title_rule_marks_corporate_finance_roles_only():
    assert pipeline.title_in_role("Senior Financial Analyst") is True
    assert pipeline.title_in_role("FP&A Manager") is True
    assert pipeline.title_in_role("Strategic Finance Associate") is True
    assert pipeline.title_in_role("Treasury Analyst") is True
    assert pipeline.title_in_role("Senior Product Designer") is False
    assert pipeline.title_in_role("Software Engineer") is False


def test_source_catalog_has_at_least_fifteen_public_json_feeds():
    sources = pipeline.load_sources()
    assert len(sources) >= 15
    assert all(source["url"].startswith("https://") for source in sources)
    assert {source["ats"] for source in sources} >= {"greenhouse", "lever"}


def test_history_first_seen_last_seen_removed_and_reopened(tmp_path):
    raw = tmp_path / "raw"
    sources = [GREENHOUSE]
    write_raw(raw, "2026-01-01", GREENHOUSE, {"jobs": [greenhouse_job("a"), greenhouse_job("b", "Product Designer")]})
    write_raw(raw, "2026-01-02", GREENHOUSE, {"jobs": [greenhouse_job("a"), greenhouse_job("c")]})
    write_raw(raw, "2026-01-03", GREENHOUSE, {"jobs": [greenhouse_job("a"), greenhouse_job("b", "Product Designer")]})
    write_raw(raw, "2026-01-04", GREENHOUSE, {"jobs": [greenhouse_job("a")]})

    rows = pipeline.build_history(raw, sources)
    by_id = {row["source_id"]: row for row in rows}

    assert [row["posting_id"] for row in rows] == sorted(row["posting_id"] for row in rows)
    assert by_id["a"]["first_seen"] == "2026-01-01"
    assert by_id["a"]["last_seen"] == "2026-01-04"
    assert by_id["a"]["status"] == "open"
    assert by_id["a"]["first_run"] == "true"

    # b was first seen in the first source file, removed, reopened, then removed again.
    assert by_id["b"]["first_seen"] == "2026-01-01"
    assert by_id["b"]["last_seen"] == "2026-01-03"
    assert by_id["b"]["removed_date"] == "2026-01-04"
    assert by_id["b"]["status"] == "removed"

    # c arrived after the first source file, was removed on the next observed file.
    assert by_id["c"]["first_seen"] == "2026-01-02"
    assert by_id["c"]["first_run"] == "false"
    assert by_id["c"]["last_seen"] == "2026-01-02"
    assert by_id["c"]["removed_date"] == "2026-01-03"


def test_status_counts_latest_run(tmp_path):
    raw = tmp_path / "raw"
    write_raw(raw, "2026-01-01", GREENHOUSE, {"jobs": [greenhouse_job("a")]})
    write_raw(raw, "2026-01-02", GREENHOUSE, {"jobs": [greenhouse_job("a"), greenhouse_job("b")]})
    history = pipeline.build_history(raw, [GREENHOUSE])
    status = pipeline.build_status(
        history,
        raw,
        [GREENHOUSE],
        run_date=date(2026, 1, 2),
        run_time=datetime(2026, 1, 2, 12, tzinfo=timezone.utc),
    )
    assert status["first_run_date"] == "2026-01-01"
    assert status["days_with_success"] == 2
    assert status["open"] == 2
    assert status["new_today"] == 1
    assert status["removed_today"] == 0
    assert status["sources"] == [{"name": "greenhouse-demo", "ok": True, "count": 2}]
