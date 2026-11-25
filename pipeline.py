#!/usr/bin/env python3
"""Fetch public job boards, rebuild history from raw snapshots, and publish a run."""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import re
import shutil
import subprocess
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
HISTORY_PATH = DATA_DIR / "history.csv"
STATUS_PATH = DATA_DIR / "status.json"
SOURCES_PATH = ROOT / "config" / "sources.json"
HISTORY_COLUMNS = [
    "posting_id",
    "source",
    "source_id",
    "employer",
    "title",
    "location",
    "department",
    "posted_date",
    "url",
    "in_role",
    "first_run",
    "first_seen",
    "last_seen",
    "status",
    "removed_date",
]

# The watched role is corporate finance and FP&A work. Keeping this rule in one function
# means a rule change is applied to every historical raw snapshot on rebuild.
ROLE_RE = re.compile(
    r"\b(?:corporate\s+finance|corporate\s+development|"
    r"financial\s+analyst|finance\s+analyst|finance\s+manager|"
    r"financial\s+planning|strategic\s+finance|revenue\s+finance|"
    r"commercial\s+finance|finance\s+business\s+partner|"
    r"treasury\s+(?:analyst|associate|manager)|financial\s+controller|"
    r"fp\s*&\s*a|fpa)\b",
    re.IGNORECASE,
)


def load_sources(path: Path = SOURCES_PATH) -> list[dict[str, str]]:
    return json.loads(path.read_text(encoding="utf-8"))


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_date(value: datetime | None = None) -> date:
    return (value or utc_now()).date()


def iso_day(value: date | str | None) -> str:
    if value is None:
        return ""
    return value.isoformat() if isinstance(value, date) else str(value)[:10]


def title_in_role(title: str) -> bool:
    """Return true for corporate finance, FP&A, and closely related titles."""

    return bool(ROLE_RE.search(title or ""))


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _greenhouse_date(job: dict[str, Any]) -> str:
    return _text(job.get("first_published") or job.get("updated_at"))[:10]


def _greenhouse_location(job: dict[str, Any]) -> str:
    location = job.get("location") or {}
    if isinstance(location, dict):
        return _text(location.get("name"))
    return _text(location)


def normalize_greenhouse(payload: dict[str, Any], source: dict[str, str]) -> list[dict[str, str | bool]]:
    rows = []
    for job in payload.get("jobs", []):
        source_id = _text(job.get("id"))
        departments = job.get("departments") or []
        department = " / ".join(
            _text(item.get("name") if isinstance(item, dict) else item)
            for item in departments
            if _text(item.get("name") if isinstance(item, dict) else item)
        )
        title = _text(job.get("title"))
        rows.append(
            {
                "posting_id": f"{source['name']}:{source_id}",
                "source": source["name"],
                "source_id": source_id,
                "employer": source["employer"],
                "title": title,
                "location": _greenhouse_location(job),
                "department": department,
                "posted_date": _greenhouse_date(job),
                "url": _text(job.get("absolute_url")),
                "in_role": title_in_role(title),
            }
        )
    return rows


def _lever_date(value: Any) -> str:
    if value in (None, ""):
        return ""
    try:
        return datetime.fromtimestamp(float(value) / 1000, tz=timezone.utc).date().isoformat()
    except (TypeError, ValueError, OverflowError):
        return _text(value)[:10]


def normalize_lever(payload: list[dict[str, Any]], source: dict[str, str]) -> list[dict[str, str | bool]]:
    rows = []
    for job in payload:
        source_id = _text(job.get("id"))
        categories = job.get("categories") or {}
        title = _text(job.get("text"))
        department = _text(categories.get("team") or categories.get("department"))
        rows.append(
            {
                "posting_id": f"{source['name']}:{source_id}",
                "source": source["name"],
                "source_id": source_id,
                "employer": source["employer"],
                "title": title,
                "location": _text(categories.get("location")),
                "department": department,
                "posted_date": _lever_date(job.get("createdAt")),
                "url": _text(job.get("hostedUrl") or job.get("applyUrl")),
                "in_role": title_in_role(title),
            }
        )
    return rows


def _date_text(value: Any) -> str:
    text = _text(value)
    if not text:
        return ""
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        for pattern in ("%b %d, %Y", "%B %d, %Y", "%m/%d/%Y"):
            try:
                return datetime.strptime(text, pattern).date().isoformat()
            except ValueError:
                continue
    return text[:10] if re.match(r"^\d{4}-\d{2}-\d{2}", text) else ""


def _workday_url(source: dict[str, str], external_path: Any) -> str:
    path = _text(external_path)
    if path.startswith("http://") or path.startswith("https://"):
        return path
    return f"{source['public_url'].rstrip('/')}/{path.lstrip('/')}"


def normalize_workday(payload: dict[str, Any], source: dict[str, str]) -> list[dict[str, str | bool]]:
    rows = []
    for job in payload.get("jobPostings", []):
        bullets = job.get("bulletFields") or []
        source_id = _text(job.get("jobReqId") or (bullets[0] if bullets else ""))
        external_path = _text(job.get("externalPath"))
        if not source_id:
            source_id = external_path.rsplit("_", 1)[-1]
        title = _text(job.get("title"))
        department = _text(job.get("department") or job.get("jobCategory") or job.get("timeType"))
        rows.append(
            {
                "posting_id": f"{source['name']}:{source_id}",
                "source": source["name"],
                "source_id": source_id,
                "employer": source["employer"],
                "title": title,
                "location": _text(job.get("locationsText") or job.get("location")),
                "department": department,
                "posted_date": _date_text(job.get("postedDate")),
                "url": _workday_url(source, external_path),
                "in_role": title_in_role(title),
            }
        )
    return rows


def _oracle_location(job: dict[str, Any]) -> str:
    locations = [_text(job.get("PrimaryLocation"))]
    for item in job.get("secondaryLocations") or []:
        if isinstance(item, dict):
            value = item.get("LocationName") or item.get("locationName") or item.get("Location")
        else:
            value = item
        if _text(value):
            locations.append(_text(value))
    return " / ".join(dict.fromkeys(value for value in locations if value))


def normalize_oracle(payload: dict[str, Any], source: dict[str, str]) -> list[dict[str, str | bool]]:
    rows = []
    items = payload.get("items") or []
    requisitions = items[0].get("requisitionList", []) if items else []
    for job in requisitions:
        source_id = _text(job.get("Id"))
        title = _text(job.get("Title"))
        rows.append(
            {
                "posting_id": f"{source['name']}:{source_id}",
                "source": source["name"],
                "source_id": source_id,
                "employer": source["employer"],
                "title": title,
                "location": _oracle_location(job),
                "department": _text(job.get("JobFamily") or job.get("JobFunction") or job.get("Department")),
                "posted_date": _date_text(job.get("PostedDate")),
                "url": f"{source['public_url'].rstrip('/')}/job/{source_id}",
                "in_role": title_in_role(title),
            }
        )
    return rows


def normalize_phenom(payload: dict[str, Any], source: dict[str, str]) -> list[dict[str, str | bool]]:
    rows = []
    jobs = (payload.get("refineSearch") or {}).get("data", {}).get("jobs", [])
    for job in jobs:
        source_id = _text(job.get("jobId") or job.get("reqId") or job.get("jobSeqNo"))
        title = _text(job.get("title"))
        category = job.get("category")
        if isinstance(category, list):
            category = " / ".join(_text(value) for value in category if _text(value))
        rows.append(
            {
                "posting_id": f"{source['name']}:{source_id}",
                "source": source["name"],
                "source_id": source_id,
                "employer": source["employer"],
                "title": title,
                "location": _text(job.get("cityStateCountry") or job.get("location") or job.get("cityState")),
                "department": _text(job.get("department") or category),
                "posted_date": _date_text(job.get("postedDate") or job.get("dateCreated")),
                "url": _text(job.get("applyUrl") or job.get("externalApply")),
                "in_role": title_in_role(title),
            }
        )
    return rows


def normalize_deloitte(payload: dict[str, Any], source: dict[str, str]) -> list[dict[str, str | bool]]:
    rows = []
    for job in payload.get("jobs", []):
        source_id = _text(job.get("guid") or job.get("reqid") or job.get("django_id"))
        title = _text(job.get("title_exact"))
        city = _text(job.get("city_exact"))
        state = _text(job.get("state_short_exact") or job.get("state_short"))
        country = _text(job.get("country_exact"))
        location = ", ".join(value for value in (city, state or country) if value)
        rows.append(
            {
                "posting_id": f"{source['name']}:{source_id}",
                "source": source["name"],
                "source_id": source_id,
                "employer": source["employer"],
                "title": title,
                "location": location,
                "department": "",
                "posted_date": _date_text(job.get("date_new") or job.get("date_added")),
                "url": f"{source['public_url'].rstrip('/')}/job/{source_id}",
                "in_role": title_in_role(title),
            }
        )
    return rows


def normalize_payload(payload: Any, source: dict[str, str]) -> list[dict[str, str | bool]]:
    if source["ats"] == "greenhouse":
        if not isinstance(payload, dict):
            raise ValueError(f"Greenhouse payload for {source['name']} is not an object")
        return normalize_greenhouse(payload, source)
    if source["ats"] == "lever":
        if not isinstance(payload, list):
            raise ValueError(f"Lever payload for {source['name']} is not a list")
        return normalize_lever(payload, source)
    if source["ats"] == "workday":
        if not isinstance(payload, dict):
            raise ValueError(f"Workday payload for {source['name']} is not an object")
        return normalize_workday(payload, source)
    if source["ats"] == "oracle":
        if not isinstance(payload, dict):
            raise ValueError(f"Oracle payload for {source['name']} is not an object")
        return normalize_oracle(payload, source)
    if source["ats"] == "phenom":
        if not isinstance(payload, dict):
            raise ValueError(f"Phenom payload for {source['name']} is not an object")
        return normalize_phenom(payload, source)
    if source["ats"] == "deloitte-json":
        if not isinstance(payload, dict):
            raise ValueError(f"Deloitte payload for {source['name']} is not an object")
        return normalize_deloitte(payload, source)
    raise ValueError(f"Unsupported ATS: {source['ats']}")


def _request_json(request: Request, timeout: int = 45) -> tuple[bytes, Any]:
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"{type(exc).__name__}: {exc}") from exc
    try:
        return raw, json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"response was not valid JSON: {exc}") from exc


def fetch_json(source: dict[str, str], timeout: int = 45) -> tuple[bytes, Any]:
    request = Request(
        source["url"],
        headers={"Accept": "application/json", "User-Agent": "job-watcher/1.0"},
    )
    return _request_json(request, timeout)


def _json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def fetch_workday(source: dict[str, str], timeout: int = 45) -> tuple[bytes, Any]:
    postings = []
    offset = 0
    limit = 20
    total = None
    while True:
        body = {
            "limit": limit,
            "offset": offset,
            "searchText": source.get("search_text", ""),
            "appliedFacets": {},
        }
        request = Request(
            source["url"],
            data=_json_bytes(body),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "job-watcher/1.0",
            },
            method="POST",
        )
        _, page = _request_json(request, timeout)
        if not isinstance(page, dict):
            raise RuntimeError(f"Workday payload for {source['name']} is not an object")
        page_jobs = page.get("jobPostings") or []
        if total is None:
            total = int(page.get("total") or 0)
        postings.extend(page_jobs)
        if not page_jobs or len(page_jobs) < limit or (total and offset + len(page_jobs) >= total):
            break
        offset += len(page_jobs)
        if offset > 10000:
            raise RuntimeError(f"Workday source {source['name']} needs a narrower search term")
    payload = {"total": total or len(postings), "jobPostings": postings}
    return _json_bytes(payload), payload


def _oracle_request_url(source: dict[str, str], offset: int) -> str:
    finder = f"findReqs;siteNumber={source['site']}"
    if source.get("search_text"):
        finder += f",keyword={source['search_text']}"
    finder += f",limit=200,offset={offset},sortBy=POSTING_DATES_DESC"
    query = "&".join(
        [
            "onlyData=true",
            "expand=requisitionList.secondaryLocations",
            f"finder={quote(finder, safe=';,=')}",
        ]
    )
    return f"{source['url']}?{query}"


def fetch_oracle(source: dict[str, str], timeout: int = 45) -> tuple[bytes, Any]:
    requisitions = []
    offset = 0
    total = None
    while True:
        request = Request(
            _oracle_request_url(source, offset),
            headers={"Accept": "application/json", "User-Agent": "job-watcher/1.0"},
        )
        _, page = _request_json(request, timeout)
        items = page.get("items") if isinstance(page, dict) else None
        if not items:
            break
        first = items[0]
        if total is None:
            total = int(first.get("TotalJobsCount") or 0)
        page_jobs = first.get("requisitionList") or []
        requisitions.extend(page_jobs)
        if not page_jobs or len(page_jobs) < 200 or (total and offset + len(page_jobs) >= total):
            break
        offset += len(page_jobs)
        if offset > 10000:
            raise RuntimeError(f"Oracle source {source['name']} needs a narrower search term")
    payload = {"items": [{"TotalJobsCount": total or len(requisitions), "requisitionList": requisitions}]}
    return _json_bytes(payload), payload


def fetch_phenom(source: dict[str, str], timeout: int = 45) -> tuple[bytes, Any]:
    jobs = []
    start = 0
    size = 500
    total = None
    while True:
        body = {
            "ddoKey": "refineSearch",
            "jobs": True,
            "from": start,
            "size": size,
            "sort": {"order": "desc", "field": "dateCreated"},
        }
        request = Request(
            source["url"],
            data=_json_bytes(body),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "job-watcher/1.0",
            },
            method="POST",
        )
        _, page = _request_json(request, timeout)
        refine = page.get("refineSearch") if isinstance(page, dict) else None
        data = refine.get("data", {}) if isinstance(refine, dict) else {}
        page_jobs = data.get("jobs") or []
        if total is None:
            total = int((refine or {}).get("totalHits") or 0)
        jobs.extend(page_jobs)
        if not page_jobs or len(page_jobs) < size or (total and start + len(page_jobs) >= total):
            break
        start += len(page_jobs)
    payload = {"refineSearch": {"totalHits": total or len(jobs), "data": {"jobs": jobs}}}
    return _json_bytes(payload), payload


def fetch_deloitte(source: dict[str, str], timeout: int = 45) -> tuple[bytes, Any]:
    jobs = []
    page_number = 1
    total_pages = None
    while True:
        params = {"job_folder": source.get("job_folder", "ALL_JOBS"), "q": source.get("search_text", ""), "page": page_number}
        request = Request(
            f"{source['url']}?{urlencode(params)}",
            headers={
                "Accept": "application/json",
                "User-Agent": "job-watcher/1.0",
                "x-origin": source.get("origin", "jobsus.deloitte.com"),
            },
        )
        for attempt in range(4):
            try:
                _, page = _request_json(request, timeout)
                break
            except RuntimeError as exc:
                if "429" not in str(exc) or attempt == 3:
                    raise
                time.sleep(5 * (attempt + 1))
        if not isinstance(page, dict):
            raise RuntimeError(f"Deloitte payload for {source['name']} is not an object")
        page_jobs = page.get("jobs") or []
        pagination = page.get("pagination") or {}
        if total_pages is None:
            total_pages = int(pagination.get("total_pages") or 1)
        jobs.extend(page_jobs)
        if not page_jobs or page_number >= total_pages:
            break
        page_number += 1
        time.sleep(float(source.get("page_delay", "0.75")))
    payload = {"jobs": jobs, "pagination": {"total_pages": total_pages or 1, "total": len(jobs)}}
    return _json_bytes(payload), payload


def fetch_source(source: dict[str, str], timeout: int = 45) -> tuple[bytes, Any]:
    if source["ats"] in {"greenhouse", "lever"}:
        return fetch_json(source, timeout)
    if source["ats"] == "workday":
        return fetch_workday(source, timeout)
    if source["ats"] == "oracle":
        return fetch_oracle(source, timeout)
    if source["ats"] == "phenom":
        return fetch_phenom(source, timeout)
    if source["ats"] == "deloitte-json":
        return fetch_deloitte(source, timeout)
    raise ValueError(f"Unsupported ATS: {source['ats']}")


def write_gzip(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wb", compresslevel=9) as handle:
        handle.write(raw)


def read_gzip_json(path: Path) -> Any:
    with gzip.open(path, "rb") as handle:
        return json.loads(handle.read().decode("utf-8"))


def source_file(day_dir: Path, source_name: str) -> Path:
    return day_dir / f"{source_name}.json.gz"


def _raw_dates(raw_dir: Path = RAW_DIR) -> list[date]:
    days = []
    if not raw_dir.exists():
        return days
    for item in raw_dir.iterdir():
        if item.is_dir():
            try:
                if any(item.glob("*.json.gz")):
                    days.append(date.fromisoformat(item.name))
            except ValueError:
                continue
    return sorted(days)


def _raw_files(raw_dir: Path = RAW_DIR) -> list[tuple[date, str, Path]]:
    found = []
    for day in _raw_dates(raw_dir):
        day_dir = raw_dir / day.isoformat()
        for path in sorted(day_dir.glob("*.json.gz")):
            found.append((day, path.name.removesuffix(".json.gz"), path))
    return found


def normalized_snapshots(
    raw_dir: Path = RAW_DIR, sources: list[dict[str, str]] | None = None
) -> tuple[dict[date, dict[str, list[dict[str, str | bool]]]], dict[str, date]]:
    sources = sources or load_sources()
    source_map = {source["name"]: source for source in sources}
    snapshots: dict[date, dict[str, list[dict[str, str | bool]]]] = defaultdict(dict)
    first_dates: dict[str, date] = {}
    for day, source_name, path in _raw_files(raw_dir):
        if source_name not in source_map:
            raise ValueError(f"Raw file {path} has no source definition")
        rows = normalize_payload(read_gzip_json(path), source_map[source_name])
        snapshots[day][source_name] = rows
        first_dates[source_name] = min(day, first_dates.get(source_name, day))
    return dict(snapshots), first_dates


def build_history(
    raw_dir: Path = RAW_DIR, sources: list[dict[str, str]] | None = None
) -> list[dict[str, str]]:
    """Rebuild the complete history from raw files, without reading history.csv."""

    sources = sources or load_sources()
    snapshots, source_first_dates = normalized_snapshots(raw_dir, sources)
    records: dict[str, dict[str, str]] = {}

    # First collect every posting. Its first-run flag is based on the first raw
    # file for its source, not merely on the first day the posting was observed.
    for day in sorted(snapshots):
        for source_name, rows in snapshots[day].items():
            for row in rows:
                posting_id = str(row["posting_id"])
                if posting_id in records:
                    continue
                record = {column: "" for column in HISTORY_COLUMNS}
                for column in (
                    "posting_id",
                    "source",
                    "source_id",
                    "employer",
                    "title",
                    "location",
                    "department",
                    "posted_date",
                    "url",
                ):
                    record[column] = str(row.get(column, ""))
                record["in_role"] = "true" if row.get("in_role") else "false"
                record["first_run"] = "true" if day == source_first_dates[source_name] else "false"
                record["first_seen"] = day.isoformat()
                record["last_seen"] = day.isoformat()
                record["status"] = "open"
                records[posting_id] = record

    # Replay each source snapshot in order. Missing source files are deliberately
    # skipped: without a raw file, the source was not observed that day.
    for day in sorted(snapshots):
        for source_name, rows in snapshots[day].items():
            seen = {str(row["posting_id"]) for row in rows}
            for record in records.values():
                if record["source"] != source_name or record["first_seen"] > day.isoformat():
                    continue
                if record["posting_id"] in seen:
                    record["last_seen"] = day.isoformat()
                    record["status"] = "open"
                    record["removed_date"] = ""
                elif record["status"] == "open":
                    record["status"] = "removed"
                    record["removed_date"] = day.isoformat()

    return [records[key] for key in sorted(records)]


def write_history(rows: Iterable[dict[str, str]], path: Path = HISTORY_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=HISTORY_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in HISTORY_COLUMNS})


def read_history(path: Path = HISTORY_PATH) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _latest_source_counts(
    raw_dir: Path, sources: list[dict[str, str]], run_date: date
) -> dict[str, int]:
    counts = {source["name"]: 0 for source in sources}
    for source in sources:
        path = source_file(raw_dir / run_date.isoformat(), source["name"])
        if path.exists():
            counts[source["name"]] = len(normalize_payload(read_gzip_json(path), source))
    return counts


def build_status(
    history: list[dict[str, str]],
    raw_dir: Path = RAW_DIR,
    sources: list[dict[str, str]] | None = None,
    run_date: date | None = None,
    run_time: datetime | None = None,
    source_results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    sources = sources or load_sources()
    run_date = run_date or utc_date(run_time)
    raw_dates = _raw_dates(raw_dir)
    counts = _latest_source_counts(raw_dir, sources, run_date)
    result_by_name = {item["name"]: item for item in (source_results or [])}
    source_status = []
    for source in sources:
        result = result_by_name.get(source["name"])
        if result is None:
            item: dict[str, Any] = {"name": source["name"], "ok": source_file(raw_dir / run_date.isoformat(), source["name"]).exists(), "count": counts[source["name"]]}
        else:
            item = {"name": source["name"], "ok": bool(result["ok"]), "count": int(result.get("count", 0))}
            if result.get("error"):
                item["error"] = result["error"]
        source_status.append(item)

    return {
        "run_time": (run_time or utc_now()).astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "first_run_date": raw_dates[0].isoformat() if raw_dates else "",
        "days_with_success": len(raw_dates),
        "open": sum(row.get("status") == "open" for row in history),
        "new_today": sum(
            row.get("first_seen") == run_date.isoformat() and row.get("first_run") != "true"
            for row in history
        ),
        "removed_today": sum(row.get("removed_date") == run_date.isoformat() for row in history),
        "sources": source_status,
    }


def write_status(status: dict[str, Any], path: Path = STATUS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(status, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def issue_body(history: list[dict[str, str]], run_date: date) -> str:
    day = run_date.isoformat()
    new = [row for row in history if row.get("first_seen") == day and row.get("first_run") != "true"]
    removed = [row for row in history if row.get("removed_date") == day]

    def listing(rows: list[dict[str, str]]) -> str:
        if not rows:
            return "- None"
        return "\n".join(
            f"- [{row['title'] or row['posting_id']}]({row['url']}) — {row['employer']} · {row['location'] or 'Location not listed'}"
            for row in rows
        )

    return f"""## Job watcher — {day}

### New postings ({len(new)})

{listing(new)}

### Removed postings ({len(removed)})

{listing(removed)}

_This issue was generated from the raw snapshots for {day}._
"""


def _run_command(args: list[str], *, check: bool = True, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=ROOT,
        check=check,
        text=True,
        input=input_text,
        capture_output=True,
    )


def update_github_issue(history: list[dict[str, str]], run_date: date) -> None:
    """Close yesterday's issue and create/update today's issue through gh."""

    if not shutil.which("gh"):
        raise RuntimeError("GitHub CLI (gh) is not installed")
    today = run_date.isoformat()
    yesterday = (run_date - timedelta(days=1)).isoformat()
    listing = _run_command(["gh", "issue", "list", "--state", "all", "--limit", "100", "--json", "number,title,state"])
    issues = json.loads(listing.stdout or "[]")
    for item in issues:
        if item.get("title") == yesterday and item.get("state") == "OPEN":
            _run_command(["gh", "issue", "close", str(item["number"])])

    body = issue_body(history, run_date)
    current = next((item for item in issues if item.get("title") == today), None)
    if current:
        _run_command(
            ["gh", "issue", "edit", str(current["number"]), "--title", today, "--body-file", "-"],
            input_text=body,
        )
        if current.get("state") != "OPEN":
            _run_command(["gh", "issue", "reopen", str(current["number"])])
    else:
        _run_command(["gh", "issue", "create", "--title", today, "--body-file", "-"], input_text=body)


def git_commit(push: bool, run_date: date) -> None:
    _run_command(["git", "add", "-A", "data/raw", "data/history.csv", "data/status.json"])
    staged = _run_command(["git", "diff", "--cached", "--quiet"], check=False)
    if staged.returncode == 0:
        return
    _run_command(["git", "commit", "-m", f"Daily run {run_date.isoformat()}"])
    if push:
        _run_command(["git", "push"])


def fetch_sources(run_date: date, raw_dir: Path, sources: list[dict[str, str]]) -> list[dict[str, Any]]:
    day_dir = raw_dir / run_date.isoformat()
    if day_dir.exists():
        shutil.rmtree(day_dir)
    day_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for source in sources:
        result: dict[str, Any] = {"name": source["name"], "ok": False, "count": 0}
        try:
            raw, payload = fetch_source(source)
            # Validate before writing: a malformed response is a failed source
            # and must not leave a misleading raw file behind.
            rows = normalize_payload(payload, source)
            write_gzip(source_file(day_dir, source["name"]), raw)
            result.update(ok=True, count=len(rows))
        except Exception as exc:  # one source must never stop the other sources
            result["error"] = str(exc)[:500]
        results.append(result)
    return results


def run_pipeline(
    *,
    run_date: date | None = None,
    run_time: datetime | None = None,
    sources: list[dict[str, str]] | None = None,
    raw_dir: Path = RAW_DIR,
    history_path: Path = HISTORY_PATH,
    status_path: Path = STATUS_PATH,
    fetch: bool = True,
    update_issue: bool = True,
    commit: bool = False,
    push: bool = False,
) -> dict[str, Any]:
    sources = sources or load_sources()
    run_time = run_time or utc_now()
    run_date = run_date or run_time.date()
    source_results = fetch_sources(run_date, raw_dir, sources) if fetch else []
    history = build_history(raw_dir, sources)
    write_history(history, history_path)
    status = build_status(history, raw_dir, sources, run_date, run_time, source_results or None)
    write_status(status, status_path)
    if update_issue:
        try:
            update_github_issue(history, run_date)
        except Exception as exc:
            # Issues are useful notification, but a transient issue/API problem
            # must not prevent the data commit that makes the run successful.
            print(f"warning: issue update failed: {exc}", file=sys.stderr)
    if commit:
        git_commit(push, run_date)
    return status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command")
    run_parser = subparsers.add_parser("run", help="fetch sources and publish one run")
    run_parser.add_argument("--date", type=date.fromisoformat, help="UTC run date, mainly for local replay")
    run_parser.add_argument("--no-issues", action="store_true")
    run_parser.add_argument("--commit", action="store_true")
    run_parser.add_argument("--push", action="store_true")
    build_parser = subparsers.add_parser("build-history", help="rebuild history and status from raw files")
    build_parser.add_argument("--date", type=date.fromisoformat, help="date to use for the status summary")
    args = parser.parse_args(argv)

    if args.command == "build-history":
        sources = load_sources()
        history = build_history()
        write_history(history)
        write_status(build_status(history, sources=sources, run_date=args.date))
        return 0
    if args.command == "run":
        run_pipeline(
            run_date=args.date,
            update_issue=not args.no_issues,
            commit=args.commit or args.push,
            push=args.push,
        )
        return 0
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
