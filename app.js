const DATA = { status: null, rows: [] };
const SHORTLIST_KEY = "job-watcher-shortlist";

async function loadData() {
  const [statusResponse, historyResponse] = await Promise.all([
    fetch("data/status.json", { cache: "no-store" }),
    fetch("data/history.csv", { cache: "no-store" }),
  ]);
  if (!statusResponse.ok || !historyResponse.ok) throw new Error("The data files could not be loaded.");
  DATA.status = await statusResponse.json();
  DATA.rows = parseCSV(await historyResponse.text());
  return DATA;
}

function parseCSV(text) {
  const rows = [];
  let row = [];
  let cell = "";
  let quoted = false;
  for (let i = 0; i < text.length; i += 1) {
    const char = text[i];
    const next = text[i + 1];
    if (char === '"' && quoted && next === '"') { cell += '"'; i += 1; }
    else if (char === '"') quoted = !quoted;
    else if (char === "," && !quoted) { row.push(cell); cell = ""; }
    else if ((char === "\n" || char === "\r") && !quoted) {
      if (char === "\r" && next === "\n") i += 1;
      row.push(cell); cell = "";
      if (row.some((value) => value !== "")) rows.push(row);
      row = [];
    } else cell += char;
  }
  if (cell || row.length) { row.push(cell); rows.push(row); }
  if (!rows.length) return [];
  const headers = rows.shift();
  return rows.map((values) => Object.fromEntries(headers.map((header, index) => [header, values[index] || ""])));
}

function escapeHTML(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" }[char]));
}

function isRole(row) { return row.in_role === "true"; }
function isOpen(row) { return row.status === "open"; }
const US_REGION_RE = /\b(?:u\.?s\.?a?\.?|united states|remote\s*(?:-|,)?\s*us|alabama|alaska|arizona|arkansas|california|colorado|connecticut|delaware|florida|georgia|hawaii|idaho|illinois|indiana|iowa|kansas|kentucky|louisiana|maine|maryland|massachusetts|michigan|minnesota|mississippi|missouri|montana|nebraska|nevada|new hampshire|new jersey|new mexico|new york|north carolina|north dakota|ohio|oklahoma|oregon|pennsylvania|rhode island|south carolina|south dakota|tennessee|texas|utah|vermont|virginia|washington|west virginia|wisconsin|wyoming|ak|al|ar|az|ca|co|ct|de|fl|ga|hi|ia|id|il|in|ks|ky|la|ma|md|me|mi|mn|mo|ms|mt|nc|nd|ne|nh|nj|nm|nv|ny|oh|ok|or|pa|ri|sc|sd|tn|tx|ut|va|vt|wa|wi|wv|wy)\b/i;
const ARKANSAS_REGION_RE = /\b(?:ar|arkansas)\b|little rock|bentonville|fayetteville|springdale|rogers|jonesboro|fort smith/i;
const TEXAS_REGION_RE = /\b(?:tx|texas)\b|austin|dallas|houston|san antonio|fort worth|plano|frisco|irving|round rock|arlington|mckinney|el paso|waco|lubbock|richardson|the woodlands/i;
function inRegion(row, region) {
  const location = row.location || "";
  if (!region) return true;
  if (region === "arkansas") return ARKANSAS_REGION_RE.test(location);
  if (region === "texas") return TEXAS_REGION_RE.test(location);
  return US_REGION_RE.test(location);
}
function today() { return (DATA.status?.run_time || "").slice(0, 10); }
function formatDate(value) {
  if (!value) return "—";
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" }).format(new Date(`${value}T00:00:00Z`));
}
function daysBetween(start, end) {
  if (!start || !end) return 0;
  return Math.max(0, Math.round((Date.parse(`${end}T00:00:00Z`) - Date.parse(`${start}T00:00:00Z`)) / 86400000));
}
function shortlist() {
  try { return new Set(JSON.parse(localStorage.getItem(SHORTLIST_KEY) || "[]")); } catch { return new Set(); }
}
function saveShortlist(items) { localStorage.setItem(SHORTLIST_KEY, JSON.stringify([...items])); }

function postingCard(row, { showDays = false } = {}) {
  const saved = shortlist().has(row.posting_id);
  const days = daysBetween(row.first_seen, today());
  return `<article class="posting-card">
    <button class="star ${saved ? "saved" : ""}" aria-label="${saved ? "Remove from" : "Add to"} shortlist" data-star="${escapeHTML(row.posting_id)}">${saved ? "★" : "☆"}</button>
    <div class="posting-main">
      <div class="eyebrow">${escapeHTML(row.employer)}${row.in_role === "true" ? " · Corporate finance role" : ""}</div>
      <h3><a href="${escapeHTML(row.url)}" target="_blank" rel="noopener">${escapeHTML(row.title || "Untitled posting")}</a></h3>
      <p class="posting-meta">${escapeHTML(row.location || "Location not listed")} · ${escapeHTML(row.department || "Department not listed")}</p>
      <p class="posting-meta">First seen ${formatDate(row.first_seen)}${showDays ? ` · ${days} day${days === 1 ? "" : "s"} open` : ""}</p>
    </div>
    <a class="apply-link" href="${escapeHTML(row.url)}" target="_blank" rel="noopener">Apply</a>
  </article>`;
}

function bindStars() {
  document.querySelectorAll("[data-star]").forEach((button) => button.addEventListener("click", () => {
    const items = shortlist();
    if (items.has(button.dataset.star)) items.delete(button.dataset.star); else items.add(button.dataset.star);
    saveShortlist(items);
    renderBrowse();
  }));
}

function renderShell() {
  const page = document.body.dataset.page;
  document.querySelectorAll(".nav-link").forEach((link) => link.classList.toggle("active", link.dataset.page === page));
  const run = document.querySelector("[data-last-run]");
  if (run && DATA.status) run.textContent = `Last run ${new Date(DATA.status.run_time).toLocaleString([], { dateStyle: "medium", timeStyle: "short" })}`;
}

function listMarkup(rows, empty = "No postings in this run.") {
  return rows.length ? rows.map((row) => postingCard(row)).join("") : `<div class="empty-state">${empty}</div>`;
}

function renderIndex() {
  const status = DATA.status;
  document.querySelector("[data-count=days]").textContent = status.days_with_success;
  document.querySelector("[data-count=open]").textContent = status.open;
  document.querySelector("[data-count=new]").textContent = status.new_today;
  document.querySelector("[data-count=removed]").textContent = status.removed_today;
  document.querySelector("[data-sources]").innerHTML = status.sources.map((source) => `<li><span class="source-dot ${source.ok ? "ok" : "bad"}"></span><span>${escapeHTML(source.name)}</span><span class="source-count">${source.ok ? `${source.count} postings` : "failed"}</span>${source.error ? `<span class="source-error">${escapeHTML(source.error)}</span>` : ""}</li>`).join("");
  const newRows = DATA.rows.filter((row) => row.first_seen === today() && row.first_run !== "true");
  const removedRows = DATA.rows.filter((row) => row.removed_date === today());
  document.querySelector("[data-new-list]").innerHTML = listMarkup(newRows);
  document.querySelector("[data-removed-list]").innerHTML = listMarkup(removedRows);
}

function renderBrowse() {
  const roleOnly = document.querySelector("#role-switch")?.checked ?? true;
  const region = document.querySelector("#region-filter")?.value || "us";
  const employer = document.querySelector("#employer-filter")?.value || "";
  const location = document.querySelector("#location-filter")?.value || "";
  const age = document.querySelector("#days-filter")?.value || "all";
  const search = (document.querySelector("#title-search")?.value || "").toLowerCase().trim();
  const sortDirection = document.querySelector("#sort-order")?.value || "newest";
  let rows = DATA.rows.filter(isOpen);
  if (roleOnly) rows = rows.filter(isRole);
  rows = rows.filter((row) => inRegion(row, region));
  if (employer) rows = rows.filter((row) => row.employer === employer);
  if (location) rows = rows.filter((row) => row.location === location);
  if (search) rows = rows.filter((row) => row.title.toLowerCase().includes(search));
  if (age !== "all") rows = rows.filter((row) => {
    const days = daysBetween(row.first_seen, today());
    return age === "0-7" ? days <= 7 : age === "8-30" ? days >= 8 && days <= 30 : days >= 31;
  });
  rows.sort((a, b) => sortDirection === "oldest" ? a.first_seen.localeCompare(b.first_seen) : b.first_seen.localeCompare(a.first_seen));
  document.querySelector("[data-browse-count]").textContent = `${rows.length} open posting${rows.length === 1 ? "" : "s"}`;
  document.querySelector("[data-browse-list]").innerHTML = listMarkup(rows, "No open postings match these filters.");
  bindStars();
}

function fillFilters() {
  const unique = (field) => [...new Set(DATA.rows.filter(isOpen).map((row) => row[field]).filter(Boolean))].sort();
  for (const [id, field] of [["employer-filter", "employer"], ["location-filter", "location"]]) {
    const select = document.querySelector(`#${id}`);
    unique(field).forEach((value) => select.insertAdjacentHTML("beforeend", `<option value="${escapeHTML(value)}">${escapeHTML(value)}</option>`));
  }
}

function chartBars(items, { max = null, color = "teal", suffix = "" } = {}) {
  if (!items.length) return `<div class="chart-empty">Not enough data yet.</div>`;
  const ceiling = max || Math.max(...items.map((item) => item.value), 1);
  return `<div class="bar-chart" style="--bar-count:${items.length}">${items.map((item) => `<div class="bar-column" title="${escapeHTML(item.label)}: ${item.value}${suffix}"><div class="bar-value">${escapeHTML(item.display ?? item.value)}</div><div class="bar ${color}" style="height:${Math.max(4, (item.value / ceiling) * 100)}%"></div><div class="bar-label">${escapeHTML(item.shortLabel ?? item.label)}</div></div>`).join("")}</div>`;
}

function median(values) {
  if (!values.length) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}

function marketSections() {
  const rows = DATA.rows;
  const lastRun = today();
  const dayKeys = [...new Set(rows.flatMap((row) => [row.first_seen, row.removed_date]).filter(Boolean))].sort();
  const newAll = Object.fromEntries(dayKeys.map((day) => [day, rows.filter((row) => row.first_seen === day && row.first_run !== "true").length]));
  const newRole = Object.fromEntries(dayKeys.map((day) => [day, rows.filter((row) => row.first_seen === day && row.first_run !== "true" && isRole(row)).length]));
  const removed = Object.fromEntries(dayKeys.map((day) => [day, rows.filter((row) => row.removed_date === day).length]));
  const open = rows.filter(isOpen);
  const employers = Object.entries(open.reduce((out, row) => { out[row.employer] = (out[row.employer] || 0) + 1; return out; }, {})).sort((a, b) => b[1] - a[1]);
  const durations = rows.filter((row) => row.first_run !== "true" && row.removed_date).map((row) => daysBetween(row.first_seen, row.removed_date));
  const eligibleDate = new Date(`${lastRun}T00:00:00Z`); eligibleDate.setUTCDate(eligibleDate.getUTCDate() - 7);
  const eligible = rows.filter((row) => row.first_run !== "true" && row.first_seen && new Date(`${row.first_seen}T00:00:00Z`) <= eligibleDate);
  const fast = eligible.filter((row) => row.removed_date && daysBetween(row.first_seen, row.removed_date) <= 7).length;
  const share = eligible.length ? fast / eligible.length : 0;
  const locations = Object.entries(open.reduce((out, row) => { const key = row.location || "Location not listed"; out[key] = (out[key] || 0) + 1; return out; }, {})).sort((a, b) => b[1] - a[1]).slice(0, 8);
  const dateLabels = (value) => formatDate(value).replace(/, \d{4}/, "");
  const allPeak = Object.entries(newAll).sort((a, b) => b[1] - a[1])[0];
  const medianDays = median(durations);
  return [
    { id: "new", finding: allPeak && allPeak[1] ? `New postings peaked on ${formatDate(allPeak[0])}.` : "New posting history is just getting started.", text: `${Object.values(newAll).reduce((a, b) => a + b, 0)} non-first-run postings were first seen across ${Object.values(newAll).filter(Boolean).length} observed days. The teal bars show all postings; coral bars isolate corporate-finance titles.`, chart: `<div class="dual-chart"><div><span class="legend teal-key">All postings</span>${chartBars(dayKeys.map((day) => ({ label: formatDate(day), shortLabel: dateLabels(day), value: newAll[day] })), { color: "teal" })}</div><div><span class="legend coral-key">Corporate finance</span>${chartBars(dayKeys.map((day) => ({ label: formatDate(day), shortLabel: dateLabels(day), value: newRole[day] })), { color: "coral" })}</div></div>` },
    { id: "removed", finding: `${Object.values(removed).reduce((a, b) => a + b, 0)} postings have been removed from their boards.`, text: "A posting counts on the day its source had a raw file and no longer listed it. If it reappears, its current status is open and its old removal date is cleared.", chart: chartBars(dayKeys.map((day) => ({ label: formatDate(day), shortLabel: dateLabels(day), value: removed[day] })), { color: "coral" }) },
    { id: "employers", finding: `${employers[0]?.[0] || "No employer"} has the largest open board.`, text: `There are ${open.length} open postings across ${employers.length} employers as of the latest run.`, chart: chartBars(employers.map(([label, value]) => ({ label, shortLabel: label, value })), { color: "teal" }) },
    { id: "days", finding: durations.length ? `The median non-first-run posting lasted ${medianDays} day${medianDays === 1 ? "" : "s"}.` : "There are not enough non-first-run removals for a median.", text: "Days open is removed date minus first-seen date. First-run postings are left out because their true start date predates monitoring.", chart: chartBars(durations.length ? Object.entries(durations.reduce((out, value) => { out[value] = (out[value] || 0) + 1; return out; }, {})).sort((a, b) => Number(a[0]) - Number(b[0])).map(([label, value]) => ({ label: `${label} days`, shortLabel: label, value })) : [], { color: "gold" }) },
    { id: "seven", finding: eligible.length ? `${Math.round(share * 100)}% were removed within seven days.` : "The seven-day measure is not eligible yet.", text: `${fast} of ${eligible.length} non-first-run postings first seen at least seven days before the latest run were removed within seven days. Open postings remain in the denominator until they are removed.`, chart: chartBars([{ label: "Within 7 days", shortLabel: "≤ 7d", value: fast, display: `${Math.round(share * 100)}%` }, { label: "Later or still open", shortLabel: "> 7d / open", value: Math.max(eligible.length - fast, 0), display: `${Math.round((1 - share) * 100)}%` }], { max: Math.max(eligible.length, 1), color: "coral" }) },
    { id: "locations", finding: `${locations[0]?.[0] || "No location"} is the most common open location.`, text: "Open postings are grouped by the location text returned by each employer board, including remote and not-listed values.", chart: chartBars(locations.map(([label, value]) => ({ label, shortLabel: label, value })), { color: "teal" }) },
  ];
}

function renderMarket() {
  const target = document.querySelector("[data-market]");
  target.innerHTML = marketSections().map((section) => `<section class="market-section" id="${section.id}"><div class="section-kicker">Market signal</div><h2>${escapeHTML(section.finding)}</h2><p>${escapeHTML(section.text)}</p>${section.chart}</section>`).join("");
}

function wireBrowse() {
  fillFilters();
  ["role-switch", "region-filter", "employer-filter", "location-filter", "days-filter", "title-search", "sort-order"].forEach((id) => document.querySelector(`#${id}`)?.addEventListener("input", renderBrowse));
  renderBrowse();
}

async function boot() {
  try {
    await loadData();
    renderShell();
    if (document.body.dataset.page === "index") renderIndex();
    if (document.body.dataset.page === "browse") wireBrowse();
    if (document.body.dataset.page === "market") renderMarket();
  } catch (error) {
    document.querySelector("main").innerHTML = `<div class="error-state"><h2>Data unavailable</h2><p>${escapeHTML(error.message)} If this is your first visit, connect once so the service worker can cache the latest report.</p></div>`;
  }
}

if ("serviceWorker" in navigator) window.addEventListener("load", () => navigator.serviceWorker.register("service-worker.js"));
boot();
