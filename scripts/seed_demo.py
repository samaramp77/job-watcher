#!/usr/bin/env python3
"""Create a small seven-day local dataset so the site is useful before first CI run."""

from datetime import date, datetime, timedelta, timezone
import json
import sys
import shutil

sys.path.insert(0, str(__file__).rsplit("/", 2)[0])
import pipeline


ROOT = pipeline.ROOT
RAW = ROOT / "data" / "raw"


def greenhouse_job(job_id, title, location, department, posted):
    return {
        "id": job_id,
        "title": title,
        "location": {"name": location},
        "departments": [{"name": department}],
        "first_published": f"{posted}T12:00:00Z",
        "absolute_url": f"https://example.com/jobs/{job_id}",
    }


def lever_job(job_id, title, location, team, posted):
    created = int(datetime.fromisoformat(f"{posted}T12:00:00+00:00").timestamp() * 1000)
    return {
        "id": job_id,
        "text": title,
        "categories": {"location": location, "team": team},
        "createdAt": created,
        "hostedUrl": f"https://example.com/jobs/{job_id}",
    }


def main():
    sources = pipeline.load_sources()
    by_name = {source["name"]: source for source in sources}
    if RAW.exists():
        shutil.rmtree(RAW)
    for offset in range(7):
        day = date(2026, 11, 13) + timedelta(days=offset)
        stamp = day.isoformat()
        greenhouse = {
            "figma": [greenhouse_job("1001", "Data Analyst, Growth", "New York, NY", "Data", stamp)],
            "cloudflare": [greenhouse_job("2001", "Product Designer", "Austin, TX", "Design", stamp)],
            "duolingo": [greenhouse_job("4001", "Senior Data Scientist", "Pittsburgh, PA", "Data", stamp)],
        }
        if offset <= 2:
            greenhouse["figma"].append(greenhouse_job("1002", "Senior Product Designer", "New York, NY", "Design", stamp))
        if offset >= 2:
            greenhouse["figma"].append(greenhouse_job("1003", "Product Analyst", "Remote", "Product", stamp))
        if offset <= 4:
            greenhouse["cloudflare"].append(greenhouse_job("2002", "Operations Analyst", "Remote", "Operations", stamp))
        if offset >= 3:
            greenhouse["cloudflare"].append(greenhouse_job("2003", "Software Engineer", "Austin, TX", "Engineering", stamp))
        if 1 <= offset <= 3:
            greenhouse["duolingo"].append(greenhouse_job("4002", "Marketing Manager", "New York, NY", "Marketing", stamp))
        if offset >= 5:
            greenhouse["duolingo"].append(greenhouse_job("4003", "Research Analyst", "Pittsburgh, PA", "Research", stamp))
        for name, jobs in greenhouse.items():
            pipeline.write_gzip(pipeline.source_file(RAW / stamp, name), json.dumps({"jobs": jobs}).encode())

        lever = []
        if offset <= 1 or offset >= 4:
            lever.append(lever_job("3001", "Senior Data Engineer", "Stockholm, Sweden", "Data", stamp))
        if offset >= 3:
            lever.append(lever_job("3002", "Content Designer", "London, UK", "Design", stamp))
        pipeline.write_gzip(pipeline.source_file(RAW / stamp, "spotify"), json.dumps(lever).encode())

    history = pipeline.build_history(RAW, sources)
    pipeline.write_history(history)
    results = [{"name": source["name"], "ok": True, "count": len(pipeline.normalize_payload(pipeline.read_gzip_json(pipeline.source_file(RAW / "2026-11-19", source["name"])), source))} for source in sources]
    status = pipeline.build_status(
        history,
        RAW,
        sources,
        run_date=date(2026, 11, 19),
        run_time=datetime(2026, 11, 19, 12, tzinfo=timezone.utc),
        source_results=results,
    )
    pipeline.write_status(status)
    print(f"Seeded {status['days_with_success']} days and {len(history)} postings.")


if __name__ == "__main__":
    main()
