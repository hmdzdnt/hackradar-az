# HackRadar AZ — discovery upgrade (2026-10-29)

- [x] Audited the two-record pipeline: two enabled sources, historical seed, unused search queries, weak relevance, date-only archival and candidate-before-write counts.
- [x] Expanded to eight access-checked official sources; disabled endpoints and unconfigured social/event platforms documented in docs/DISCOVERY.md.
- [x] Modular HTML, RSS/Atom, sitemap, structured-event and public Telegram announcement intake; reviewed official-link corroboration.
- [x] Optional AZ/EN/RU official search API, disabled by default; no paid service activated.
- [x] Evidence-based Azerbaijan venue/eligibility checks, explicit dates/timestamps and quarantine decisions.
- [x] Independent pre-insert expiry protection, preserved historical rows, stronger event identity and corrected-date updates.
- [x] Additive migration 002 prepared with exact-time lifecycle, run summaries, public-only RLS and expired-insert guard.
- [x] Existing-schema fallback tested; explicit timing remains in private evidence until migration.
- [x] Per-source reports and accurate write outcomes; source isolation and bounded request/candidate budgets.
- [x] Existing schedule retained: 00/06/12/18 Asia/Baku; manual dispatch supported.
- [x] 64 unit tests passed (46 Python + 18 JavaScript), embedded PostgreSQL migrations/RLS checks, Worker runtime and frontend build.
- [x] Eight-source live dry run: 19 HTTP requests, no source errors, SOCAR eligible; no database writes or fabricated events.
- [x] Final targeted SOCAR smoke passed after validation changes.

## Manual deployment and limitations

Apply supabase/migrations/002_discovery_quality.sql once in the existing Supabase project only after review. It has not been applied remotely. The writer works with migration 001; precise end-time publication and persistent run summaries require 002. Existing records are never deleted. Unknown past-start/end candidates can be held in the Actions review artifact without insertion.

No secret values were read, changed or committed. Optional search needs manual approval of a genuinely free account, repository secret DISCOVERY_SEARCH_API_KEY and variable DISCOVERY_SEARCH_ENABLED=true; otherwise it stays disabled. Social platforms and event aggregators are not broadly monitored without reviewed compliant endpoints. Freeform/JS-only or ambiguous announcements may require manual review. New records appear through the existing live API; an already-open page needs refresh. Production cloud credentials are unavailable here; no direct Cloudflare deployment or Supabase migration is claimed.

## Migration 002 safety review

- Confirmed migration 001 uses published-and-verified RLS and a security-invoker public view. Added a restrictive anon/authenticated SELECT guard and reasserted RLS in 002.
- Replaced unsafe direct JSON timestamp casts with a temporary, strict ISO/offset parser; invalid, ambiguous, date-mismatched or contradictory timings are skipped without touching their rows.
- Added 24 evidence regression cases plus anon/authenticated tests under an accidental broad SELECT policy, private-column/RPC/write denial and retained-record checks. Included in npm run test:db.
- No production database was connected to or changed. Migration 002 remains a one-time, manually reviewed migration for schema 001.
