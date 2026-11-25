# Corporate Finance Job Watcher

[![Tests](https://github.com/samaramp77/job-watcher/actions/workflows/tests.yml/badge.svg)](https://github.com/samaramp77/job-watcher/actions/workflows/tests.yml)

Corporate Finance Job Watcher is a reproducible daily monitor for public employer job boards. It watches corporate-finance and FP&A opportunities across fintech and technology employers, keeps every posting returned by each board, compares daily snapshots, and publishes the result to GitHub Pages.

The role rule is title-only. A posting is `in_role=true` when its title contains `corporate finance`, `corporate development`, `financial analyst`, `finance analyst`, `finance manager`, `financial planning`, `strategic finance`, `revenue finance`, `commercial finance`, `finance business partner`, `treasury analyst`, `treasury associate`, `treasury manager`, `financial controller`, `FP&A`, or `FPA` (case-insensitive). Every other posting stays in the history and can be shown with Browse's **All postings** switch.

## Sources

Every source is a no-login public JSON endpoint provided by the employer's applicant-tracking system. The pipeline never reads a job-board HTML page. The source catalog contains 16 employers, which is above the required minimum of 15.

| Source | Employer | ATS | Raw format | Endpoint |
| --- | --- | --- | --- | --- |
| `affirm` | Affirm | Greenhouse | JSON | `boards-api.greenhouse.io/v1/boards/affirm/jobs?content=true` |
| `brex` | Brex | Greenhouse | JSON | `boards-api.greenhouse.io/v1/boards/brex/jobs?content=true` |
| `coinbase` | Coinbase | Greenhouse | JSON | `boards-api.greenhouse.io/v1/boards/coinbase/jobs?content=true` |
| `robinhood` | Robinhood | Greenhouse | JSON | `boards-api.greenhouse.io/v1/boards/robinhood/jobs?content=true` |
| `sofi` | SoFi | Greenhouse | JSON | `boards-api.greenhouse.io/v1/boards/sofi/jobs?content=true` |
| `stripe` | Stripe | Greenhouse | JSON | `boards-api.greenhouse.io/v1/boards/stripe/jobs?content=true` |
| `ramp` | Ramp | Greenhouse | JSON | `boards-api.greenhouse.io/v1/boards/ramp/jobs?content=true` |
| `chime` | Chime | Greenhouse | JSON | `boards-api.greenhouse.io/v1/boards/chime/jobs?content=true` |
| `block` | Block | Greenhouse | JSON | `boards-api.greenhouse.io/v1/boards/block/jobs?content=true` |
| `figma` | Figma | Greenhouse | JSON | `boards-api.greenhouse.io/v1/boards/figma/jobs?content=true` |
| `cloudflare` | Cloudflare | Greenhouse | JSON | `boards-api.greenhouse.io/v1/boards/cloudflare/jobs?content=true` |
| `duolingo` | Duolingo | Greenhouse | JSON | `boards-api.greenhouse.io/v1/boards/duolingo/jobs?content=true` |
| `gitlab` | GitLab | Greenhouse | JSON | `boards-api.greenhouse.io/v1/boards/gitlab/jobs?content=true` |
| `asana` | Asana | Greenhouse | JSON | `boards-api.greenhouse.io/v1/boards/asana/jobs?content=true` |
| `lyft` | Lyft | Greenhouse | JSON | `boards-api.greenhouse.io/v1/boards/lyft/jobs?content=true` |
| `wealthfront` | Wealthfront | Lever | JSON | `api.lever.co/v0/postings/wealthfront?mode=json` |

The catalog was checked during setup and these boards were below 5,000 postings, so no search term was necessary. If a board later grows beyond 5,000, its catalog URL must be changed to include a role search term and this section must document that term.

## Pipeline and replay

GitHub Actions runs `python pipeline.py run --commit --push` every day at 12:17 UTC. The run date is the UTC date of the run. For each source, the pipeline saves the exact JSON response compressed at `data/raw/YYYY-MM-DD/<source>.json.gz`. A failed source writes no raw file, records `ok: false`, and does not stop the other sources, history build, status write, Issue update, or commit.

The raw archive is the only input to the history build. Running the command below does not call the network and reproduces `data/history.csv` from all raw files:

```bash
python pipeline.py build-history
```

The history builder processes days in order. A posting first seen in a source's first raw file has `first_run=true`. Every observed listing updates `last_seen` and makes the posting open. An open posting is marked removed when its source has a raw file for that day and no longer lists it. If it reappears later, it becomes open again, its `removed_date` is cleared, and its original `first_seen` remains unchanged. Rows are sorted by `posting_id`.

Each daily Issue is titled with the UTC date and lists new and removed postings with employer, location, and an application link. The previous day's open Issue is closed. A rerun on the same date replaces that day's raw directory, rebuilds all history, and edits/reopens the existing date Issue instead of creating a second current-day Issue. The Issue is still created when there are no changes.

## Data definitions

`data/history.csv` has one row per unique posting and these fixed columns:

| Column | Meaning | Unit/format |
| --- | --- | --- |
| `posting_id` | Source name plus the source's own posting ID | text, `source:source_id` |
| `source` | Catalog key for the ATS source | text |
| `source_id` | Employer-board ID for the posting | text |
| `employer` | Employer name from the source catalog | text |
| `title` | Posting title returned by the board | text |
| `location` | Location returned by the board | text |
| `department` | Department/team returned by the board | text |
| `posted_date` | Source-reported posting date when available | UTC `YYYY-MM-DD` or empty |
| `url` | Direct application URL | URL text |
| `in_role` | Whether the title matches the corporate-finance rule | `true`/`false` |
| `first_run` | Whether the posting appeared in the source's first raw file | `true`/`false` |
| `first_seen` | First day this posting appeared in the archive | UTC `YYYY-MM-DD` |
| `last_seen` | Most recent day the source listed the posting | UTC `YYYY-MM-DD` |
| `status` | Whether the posting is currently listed or removed | `open`/`removed` |
| `removed_date` | Day the source first observed the posting missing after it was open | UTC `YYYY-MM-DD` or empty |

`data/status.json` contains `run_time` (UTC timestamp), `first_run_date`, `days_with_success`, `open`, `new_today`, `removed_today`, and `sources`. Each source entry contains `name`, `ok`, `count`, and, when needed, an error message. `new_today` excludes first-run postings; `removed_today` counts postings whose current removed date is the latest run date.

## Site

- `index.html` is Today: the latest run time, all source statuses, the four status counts, and new/removed posting lists.
- `browse.html` is Browse: role/all switch, employer/location/days-open filters, title search, first-seen sort, application links, and a browser-local starred shortlist.
- `market.html` is Market: six history-derived findings and charts for new postings per day, removed postings per day, open postings by employer, median days open, share removed within seven days, and top open locations.

All calculations on the site happen in the browser from `data/history.csv` and `data/status.json`. The manifest and service worker make the site installable and cache the last loaded data for offline use. When online, data requests go to the network first and update the cache.

## Repository files

- `.github/workflows/tests.yml` runs pytest on every push and pull request.
- `.github/workflows/daily.yml` runs the daily fetch/build/Issue/commit job on schedule and supports manual runs.
- `.github/workflows/pages.yml` deploys the root static site to GitHub Pages.
- `config/sources.json` lists every employer, ATS, and JSON endpoint.
- `pipeline.py` fetches sources, converts ATS payloads, classifies titles, rebuilds history/status, updates Issues, and commits daily data.
- `tests/test_pipeline.py` covers Greenhouse and Lever conversion, the corporate-finance title rule, first-run semantics, last-seen updates, removals, reopenings, and status counts.
- `scripts/seed_demo.py` creates a deterministic seven-day fixture for local site preview; scheduled runs use live endpoints.
- `data/raw/` stores compressed JSON snapshots by UTC date and source.
- `data/history.csv` is the derived one-row-per-posting history.
- `data/status.json` is the latest-run summary used by Today.
- `index.html`, `browse.html`, and `market.html` are the three site pages.
- `app.js` loads the data, filters postings, maintains the shortlist, and computes Market findings/charts.
- `styles.css` defines the shared responsive visual system.
- `manifest.webmanifest` declares the installable app.
- `service-worker.js` provides the offline shell and network-first data caching.
- `icon.svg` is the app icon.
- `pyproject.toml` configures the Python project and pytest discovery.
- `requirements-dev.txt` lists the test dependency.
- `README.md` documents the sources, data definitions, rules, commands, and repository layout.

## Local commands

```bash
python3 scripts/seed_demo.py
python3 pipeline.py build-history
python3 -m pytest -q
python3 -m http.server 8000
```

Open `http://localhost:8000/` for the site. The public repository and live Pages URL are added after the first GitHub push.
