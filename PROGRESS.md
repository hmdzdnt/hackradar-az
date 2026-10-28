# HackRadar AZ

- [x] React/Vite/Tailwind project and separate Pages/Worker deployment configurations
- [x] Supabase migration, publication RLS, private evidence, constraints, indexes and archival
- [x] Real HTML/RSS/Atom/sitemap connectors, robots/SSRF checks, retries and source tracking
- [x] Evidence-based extraction, verification, source updates and edition-aware deduplication
- [x] Public API, validated filters, grounded Gemini selection and deterministic Azerbaijani fallback
- [x] SQLite Durable Object anonymous quotas and bounded AI budget
- [x] Responsive dark UI, animated white rounded borders, search, seven filters, details and calendar
- [x] Scheduled discovery: 02/08/14/20 UTC = 06/12/18/00 Asia/Baku
- [x] 32 unit tests passed: 19 Python + 13 JavaScript; zero failing
- [x] Actual migration passed embedded PostgreSQL RLS, private-column, write, uniqueness, date and archive checks
- [x] Worker bundle and workerd runtime passed, including SQLite 8/min quota enforcement
- [x] Latest live-source smoke: 2 verified events, 0 source errors; snapshot contains actual SOCAR and BEU announcements
- [x] Production frontend build passed; fixtures never enter production records

## External blockers / verification limits

No Supabase/Cloudflare/Gemini credentials are configured. Remote Supabase writes, live Gemini calls, GitHub schedule activation and production deployment remain unverified. Local source snapshot and deterministic assistant work without credentials. Browser visual QA was unavailable. Metro connector is explicitly disabled after a real HTTP 404. Initial intermittent DNS failures prompted bounded DNS retries; partial diagnostic runs cannot replace the verified snapshot.

Deployment: prepared, not live. Setup instructions and free-tier limits are in README.md.
