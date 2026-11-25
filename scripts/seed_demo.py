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
    if RAW.exists():
        shutil.rmtree(RAW)
    start = date(2026, 11, 18)
    for offset in range(7):
        day = start + timedelta(days=offset)
        stamp = day.isoformat()
        for index, source in enumerate(sources, start=1):
            prefix = str(index * 1000)
            jobs = [
                greenhouse_job(
                    f"{prefix}1",
                    "Senior Financial Analyst",
                    "Chicago, IL" if index % 2 else "New York, NY",
                    "Finance",
                    stamp,
                )
            ]
            if offset >= 2 and index % 3 == 0:
                jobs.append(
                    greenhouse_job(
                        f"{prefix}2",
                        "Strategic Finance Associate",
                        "Remote",
                        "Corporate Finance",
                        stamp,
                    )
                )
            if offset <= 3 and index % 4 == 0:
                jobs.append(
                    greenhouse_job(
                        f"{prefix}3",
                        "Senior Product Designer",
                        "Austin, TX",
                        "Design",
                        stamp,
                    )
                )
            if source["ats"] == "lever":
                lever_jobs = [
                    lever_job(job["id"], job["title"], job["location"]["name"], job["departments"][0]["name"], stamp)
                    for job in jobs
                ]
                pipeline.write_gzip(pipeline.source_file(RAW / stamp, source["name"]), json.dumps(lever_jobs).encode())
            else:
                pipeline.write_gzip(
                    pipeline.source_file(RAW / stamp, source["name"]),
                    json.dumps({"jobs": jobs}).encode(),
                )

    history = pipeline.build_history(RAW, sources)
    pipeline.write_history(history)
    results = [
        {
            "name": source["name"],
            "ok": True,
            "count": len(
                pipeline.normalize_payload(
                    pipeline.read_gzip_json(pipeline.source_file(RAW / "2026-11-24", source["name"])),
                    source,
                )
            ),
        }
        for source in sources
    ]
    status = pipeline.build_status(
        history,
        RAW,
        sources,
        run_date=date(2026, 11, 24),
        run_time=datetime(2026, 11, 24, 12, tzinfo=timezone.utc),
        source_results=results,
    )
    pipeline.write_status(status)
    print(f"Seeded {status['days_with_success']} days and {len(history)} postings.")


if __name__ == "__main__":
    main()
