# Discovery v2: coverage, review and deployment

## Audit of the original two-record system

Only BEU and SOCAR were enabled; Metro returned 404 and was disabled. BEU had a hardcoded 2025 CyberCell seed. Search queries were unused constants. The Azerbaijan check accepted any country/city mention. Verification allowed ended events to be inserted; archival was date-only. Candidate counts were incremented before successful writes. No discovery AI was enabled: the Gemini integration is an optional assistant selector, and its default is disabled.

## Active public sources

The following endpoints passed bounded, robots-aware public access checks in this environment. Availability can change; each actual run records its observed coverage, including failures. Successful access does not imply that a site currently has an eligible announcement.

| Key | Publisher | Coverage |
|---|---|---|
| beu | Baku Engineering University | University/student announcements |
| ada | ADA University | University news/events |
| aztu | Azerbaijan Technical University | University news |
| edu | Ministry of Science and Education | Public announcements |
| socar | SOCAR Hackathon | Official event landing page and audited adapter |
| azercell | Azercell | Technology company announcements |
| ict | Institute of Information Technology | Public research/technology announcements |
| sup | SUP.VC | Innovation consultancy/accelerator announcements |

The historical CyberCell seed is removed. Already-stored CyberCell records are retained and archived. `sources.json` is the reviewed host registry; do not mark a third-party publisher trusted merely because its page is accessible.

## Sources not currently monitored

- Metro: inspected article returned HTTP 404.
- ASOIU: inspected news endpoint returned HTTP 404.
- UNEC RSS: HTTP 401; no authentication bypass attempted.
- Ministry of Digital Development and Transport: access restriction encountered.
- IDDA, BHOS and SABAH.HUB: DNS failures in this environment. This does not establish that they are unavailable to all visitors; they need a successful endpoint/access review before activation.
- Instagram, Facebook, LinkedIn, X and TikTok: no approved API/feed configured; restricted social pages are not scraped.
- Telegram: public channel HTML adapter exists, but no channel is configured/reviewed. It reads public announcement text and post URLs only, without profiles, comments, members or contact extraction.
- YouTube: public RSS/Atom announcement intake is supported, but no reviewed channel feed is configured. No video/comments scraping or API quota use occurs.
- Devpost, Eventbrite and Luma: generic public event-page JSON-LD intake exists. No broad platform crawl/API account is enabled. Configure a reviewed event/feed source and permitted host explicitly; third-party pages remain quarantined until corroborated against a trusted official page or reviewed manually.

For an approved public feed, use `kind: rss`; for XML maps, `kind: sitemap`, or add explicit `feeds`/`sitemaps` to a source. Nested sitemaps are limited to two children and one level. For a reviewed Telegram channel source, set `adapter: telegram` and its public `/s/channel` URL with `t.me` in `hosts`. All page requests still obey robots and access restrictions. Source trust, explicit event dates, and physical-location/eligibility evidence remain mandatory for publication. An RSS publication timestamp is never used as an event date by itself.

## Optional AZ/EN/RU search (manual opt-in)

The official Brave Search API adapter rotates Azerbaijani, English and Russian queries, including hackathon/hackaton/hakaton, coding marathons, innovation challenges, AI and cybersecurity, plus event/social domains. It uses at most four queries and twenty links per run; only reviewed enabled hosts are fetched. Unknown or restricted domains are recorded as unfetched leads with a reason, not silently treated as monitored sources. Accessible untrusted announcements may be cross-checked using a directly linked, trusted official page; failing corroboration leaves them unpublished.

No search service is used by default. **Do not enable a paid account or paid billing.** If a genuine free tier is available to your account and its terms permit this usage, manually add repository secret `DISCOVERY_SEARCH_API_KEY`, then repository Actions variable `DISCOVERY_SEARCH_ENABLED=true`. Existing Supabase secrets remain the only mandatory secrets. If no suitable free plan is available, leave search disabled. There is no automatic paid fallback, search-engine HTML scraping, CAPTCHA handling or account login.

## Validation and review

Physical Azerbaijan venue evidence or explicit Azerbaijan-based participant eligibility is required. An organizer's country/address, a sponsor mention or a previous winner's nationality is insufficient. Foreign structured venues are rejected even if the article mentions Baku. A generic innovation challenge requires evidence of hackathon-style team prototyping and a bounded coding period; otherwise it is quarantined.

Unknown/ambiguous dates, missing event end, unclear event format and untrusted announcements stay unpublished. Review unpublished rows in Supabase: `hackathons.evidence.review` contains the decision and reasons. The Actions artifact also includes a `quarantine` array. A past start with unknown end is held in that artifact without inserting a possibly historical new record. Published fields never contain internal review evidence. No AI invents details.

Never-ended means upcoming or ongoing: upcoming events with closed registration are accepted and labeled closed. Clearly expired new records are rejected before POST, independently of parser flags. Existing matching expired records can be marked archived; no historical record is deleted. The additive SQL migration also blocks expired INSERTs while permitting updates to historical rows.

Canonical URLs remove fragments and known tracking parameters. Organizer, normalized/quoted title, dates and source identity support duplicate matching; shared landing URLs alone do not merge different annual editions. Corrected dates for the same event update the existing record. Incomplete reposts do not erase verified official facts. Identical semantic records still refresh source hashes and verification timestamps.

## Schedule, budgets and diagnostics

The existing UTC schedule `0 2,8,14,20 * * *` remains: 00/06/12/18 Asia/Baku. Manual dispatch is available. GitHub can delay scheduled runs. Limits per run: eight reviewed sources, eighty HTTP requests including robots/retries, forty candidates, twelve candidates per source, six page/feed/map documents per source, and a 45-second source timeout. More than eight enabled sources rotate between runs. Search is additionally limited to four requests; corroboration shares the page-request budget.

Reports are both structured logs and the `discovery-report` Actions artifact (`discovery.json`, retained three days). Counters: discovered, accepted, duplicate, expired, rejected, quarantined, written, write_errors and source_errors. In a normal run, accepted/written count persistence outcomes, not just extracted candidates; dry runs simulate decisions without writes. Per-source coverage includes status, page/request counts and sanitized errors. Disabled/deferred sources are explicitly listed. Rejected also counts pages with no identifiable hackathon announcement.

One source's error does not stop subsequent sources. Total access failure or any database write failure produces a failed run after diagnostics; ordinary partial source availability is reported as partial. A successful zero-event run is valid when accessible sources have no eligible announcements. A database-backed run still creates its `discovery_runs` row before crawling. DB diagnostics expose method/table, HTTP status and error code, never secret values or response bodies.

## Safe manual migration

**Prepared, not applied remotely:** `supabase/migrations/002_discovery_quality.sql`. Review and apply this file once in the existing project's Supabase SQL Editor; do not rerun 001. It adds explicit start/end timestamps, timezone, location, announcement URL, run summaries, a new-record expiry guard, and a dynamic lifecycle view. It preserves existing rows, public-view column order and published-only RLS. Embedded PostgreSQL tests exercise both migrations and 24 timing-evidence cases. Backfill accepts only valid, timezone-explicit ISO strings aligned with stored Baku dates; nulls, malformed values, timezone-free strings and contradictory ranges stay null for review. Rows with no valid backfill are not updated; valid backfills refresh `updated_at` through the existing trigger. A restrictive published-and-verified SELECT policy protects anon/authenticated reads even if another permissive policy is added. The temporary parser is removed before commit.

The Python writer detects the old schema and continues safely without new columns; timing evidence remains private in JSON until migration. After migration, exact timestamp fields are saved and the API receives the additional fields through its existing public view. Date-only events have null timestamps and archive at the midnight following their end date in Asia/Baku. Explicit timestamps are preserved, with display dates converted to Baku. There is no guessed actual event time.

The shared API/frontend lifecycle calculation supports upcoming, ongoing and archived at request/render time, including existing date-only rows. API defaults exclude archived events; `archive=all`, `archive=only`, or `lifecycle=archived|ongoing|upcoming` select their respective sets. Status changes require no new frontend deployment. Existing frontend deployments retain date-only behavior until their updated bundle is deployed. A page already open needs a refresh to fetch newly discovered records.

## Checks

```sh
.venv/bin/python -m unittest discover -s tests -v
npm run check
.venv/bin/python -m discovery.run --dry-run --output artifacts/discovery-live.json
```

Use `--source socar` (repeatable) for a targeted smoke check. Dry runs do not write to Supabase. Reports contain actual source observations; synthetic fixtures remain in tests only and are never exported as production events. Do not interpret a dry-run accepted count as a newly inserted event count.
