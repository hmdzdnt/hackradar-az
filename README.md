# HackRadar AZ

Azerbaijan hackathon discovery. React/Vite/Tailwind frontend on Cloudflare Pages, a Cloudflare Worker public API, Supabase PostgreSQL, and Python discovery scheduled by GitHub Actions. No always-running server, login, subscriptions or notifications.

## Local setup

Requires Node 22+ and Python 3.12+.

```sh
npm ci
python -m venv .venv
.venv/bin/pip install -r requirements.txt
npm run dev
```

The default frontend reads `public/events.json`, a snapshot exported from actual official-source discovery, with its verification timestamp visibly labeled. It is not a fixture or an automatically refreshed database. Search, filters, details, calendar and deterministic assistant work in this mode. Stale registration claims become unknown after seven days, and expired records move out of active results. Set `VITE_API_BASE_URL` before building to use the live database-backed API. API failure shows an error rather than quietly switching datasets.

## Discovery upgrade

See [discovery coverage and safe migration](docs/DISCOVERY.md). Migration `002_discovery_quality.sql` is additive and requires manual review/application; the upgraded writer remains compatible with migration 001 until then. No remote migration is applied by GitHub Actions.

## Supabase

Create a **Free** Supabase project and run `supabase/migrations/001_initial.sql` in the SQL editor (or `supabase db push` with a linked CLI project). Tables: `hackathons`, `sources`, `event_sources`, `discovery_runs`. RLS allows public SELECT only for verified, published events, including explicitly requested archive data. `public_hackathons` derives expired/stale registration states at read time. Private evidence, run logs and source configuration are inaccessible to anonymous callers. Only discovery receives the service-role key.

Export `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` in your shell/CI secrets. `.env` is an example convention, not implicitly loaded by Python: use your shell or CI environment. Never put service-role or Gemini keys in `VITE_*` variables.

```sh
.venv/bin/python -m discovery.run --dry-run --output artifacts/discovery-live.json
.venv/bin/python -m discovery.run --output artifacts/discovery.json
```

Dry run fetches real sources and does not write to Supabase. The normal run stores verified events and unpublished review candidates, tracks source hashes, updates existing source identities, merges matching event editions, and archives expired events. Unknown values stay SQL null. Sources returning errors do not make fabricated records or delete existing events. Partial failures are recorded; total source failure exits nonzero. Eight reviewed official endpoints are enabled across universities, government, technology companies and innovation organizations. Disabled endpoints and unconfigured social/event platforms are explicitly documented in `docs/DISCOVERY.md`. The SOCAR event-page adapter extracts facts from its actual dates table and explicit rules. Generic HTML, RSS/Atom and keyword-filtered XML sitemap connectors are implemented and tested. Expand only with reviewed public hosts and inspected extraction evidence. An optional, explicitly enabled official search API rotates AZ/EN/RU queries; it is disabled by default. No search-engine HTML or restricted-social scraping is enabled.

Source requests obey robots.txt, HTTPS host allowlists, public-address checks, size limits, crawl delays, timeouts and bounded retries. 401/403/429 and unavailable robots policies are not bypassed. Unknown event dates or untrusted sources prevent publication. JSON-LD and explicit event-date prose can verify candidates; date-only publication timestamps cannot. The initial parser intentionally favors omissions over guesses. Review unpublished rows in Supabase and correct/verify their source evidence manually when necessary.

To refresh the checked-in snapshot deliberately after a real dry run:

```sh
.venv/bin/python scripts/export-snapshot.py artifacts/discovery-live.json
```

This exports only verified records and excludes internal evidence. It is optional; scheduled production uses the database directly, so it needs no Git write token or repeated frontend builds.

## Cloudflare API

Use a **Workers Free** account, without a paid plan. `worker/wrangler.toml` creates a SQLite Durable Object for atomic anonymous quotas. Configure these through `npx wrangler secret put NAME --config worker/wrangler.toml`:

- `SUPABASE_URL`
- `SUPABASE_ANON_KEY` (Supabase anon JWT/publishable key; not the service key)
- `RATE_LIMIT_SALT` (generate a random secret, e.g. `openssl rand -hex 32`)
- `GEMINI_API_KEY` (optional)

For local API work put those names in an ignored `worker/.dev.vars` and run `npm run worker:dev`. Set `VITE_API_BASE_URL=http://localhost:8787` for frontend development. Set `ALLOWED_ORIGIN` in `worker/wrangler.toml` to the exact frontend production origin, then `npm run deploy:api`. No wildcard CORS. Do not log secrets.

API: `GET /api/health`, `GET /api/events`, `GET /api/events/:uuid`, `GET /api/stats`, `POST /api/assistant` with `{"question":"..."}`. Event filters: `q, city, format, topic, status, from, to, age, prize, archive, lifecycle`. Default excludes archive; `archive=all` includes it. Up to 5,000 records are loaded in bounded pages with an explicit `limited` flag. Edge database cache: five minutes. Dates and registration are reevaluated at request time.

Assistant: 3–600 characters, 4 KB maximum JSON body; salted anonymous IP hashes, 8 requests/minute, 40/day/person, 2,000/day/site. Gemini selection is capped at 15/day/person and 80/day/site (including failed attempts). Set `GEMINI_ENABLED="true"` only with a Gemini project that has free-tier access and **no paid billing enabled**; availability/quotas vary. Default is deterministic fallback. Gemini selects only known IDs and a response focus; all factual prose is rendered in Azerbaijani from database fields with source links. It cannot introduce a new event or invent eligibility. 429, malformed output, model unavailability and timeouts fall back without retries. Source-provided English rule excerpts are preserved verbatim rather than mistranslated into new requirements.

## Cloudflare Pages

Create a **Pages Free** project using this repository:

- Build command: `npm run build`
- Output directory: `dist`
- Environment: `VITE_API_BASE_URL=https://hackradar-az-api.<account>.workers.dev`
- Node version: `22`

Or deploy the build with `npm run deploy:pages`. Pages configuration is in root `wrangler.toml`; Worker configuration is separate in `worker/wrangler.toml`. SPA redirects and security headers are in `public/`. The default CSP permits the `*.workers.dev` API; if you use a custom API domain, add its exact HTTPS origin to `connect-src` in `public/_headers`. Pages routing supports direct links to detail/calendar pages. Preview origins need their own Worker allowed-origin setting for API QA.

## Scheduling and budget

Enable Actions in a GitHub repository and set repository secrets `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`. The scheduled workflow uses `0 2,8,14,20 * * *` UTC, corresponding to 00:00/06:00/12:00/18:00 Asia/Baku. GitHub may delay scheduled runs, particularly on the hour. The workflow must be on the default branch; inactive public repositories may have schedules disabled by GitHub. Manual dispatch is provided; overlapping runs are serialized.

Operate exclusively on free plans: no custom domain purchase, paid search, paid Gemini billing, KV/R2, always-on hosting or paid database. Prefer a public GitHub repository for free standard hosted Actions minutes. Keep Cloudflare paid upgrades disabled, set GitHub spending to zero, and use a Supabase Free project. Free services have capacity/availability limits; the correct behavior at quota exhaustion is degraded service, not automatic paid upgrades. Source requests and AI calls are bounded. Supabase free projects can pause and Gemini free models can be unavailable; reconnect/restart services as needed. This project does not create provider accounts or enable billing.

## Verification

```sh
.venv/bin/python -m unittest discover -s tests -v
npm run check
```

`npm run check` also bundles the Worker and runs its actual workerd/SQLite Durable Object runtime with network mocked to the verified source snapshot. Browser visual QA was unavailable in the execution environment.

Tests cover connectors, extraction, dates, deduplication, SSRF/robots, mocked PostgREST writes, shared search/filters/calendar logic, endpoints, input validation, rate-limit responses and grounded AI fallback. `test:db` runs the actual migration against embedded PostgreSQL (PGlite), including RLS and constraints; fixtures exist only inside tests and that transient database. Remote Supabase connectivity and live Gemini responses require credentials and are not implied by local tests. Live-source smoke reports are ignored under `artifacts/`. No live deployment is claimed until provider deploy and endpoint checks succeed.
