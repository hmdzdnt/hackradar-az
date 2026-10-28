begin;
create table public.sources (
 id uuid primary key default gen_random_uuid(), name text not null, url text unique not null check (url ~ '^https://'),
 kind text not null check (kind in ('html','rss','sitemap')), trusted boolean not null default false,
 enabled boolean not null default true, last_success_at timestamptz, created_at timestamptz not null default now()
);
create table public.hackathons (
 id uuid primary key default gen_random_uuid(), fingerprint text unique not null,
 title text not null check (length(title) between 3 and 300), organizer text, description text,
 city text, format text check (format in ('onsite','online','hybrid')), start_date date, end_date date,
 registration_deadline timestamptz, registration_url text check (registration_url ~ '^https://'),
 official_source_url text not null check (official_source_url ~ '^https://'),
 age_min integer check(age_min between 0 and 100), age_max integer check(age_max between 0 and 100),
 age_restrictions text, team_requirements text, prize_info text, has_prize boolean, topics text[],
 registration_status text not null default 'unknown' check (registration_status in ('open','closed','unknown')),
 registration_evidence text, verified boolean not null default false, published boolean not null default false,
 archived boolean not null default false, evidence jsonb not null default '{}',
 last_verified_at timestamptz, created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
 check (end_date is null or start_date is null or end_date >= start_date),
 check (age_min is null or age_max is null or age_max >= age_min),
 check (not published or (verified and last_verified_at is not null and start_date is not null)),
 check (registration_status != 'open' or (registration_evidence is not null and registration_url is not null))
);
create table public.event_sources (
 event_id uuid references public.hackathons on delete cascade, source_id uuid references public.sources on delete cascade,
 url text not null check(url ~ '^https://'), content_hash text not null, last_seen_at timestamptz not null default now(),
 primary key(event_id, url)
);
create table public.discovery_runs (
 id uuid primary key default gen_random_uuid(), started_at timestamptz not null default now(), finished_at timestamptz,
 status text not null check(status in ('running','success','partial','failed')), discovered integer not null default 0,
 published integer not null default 0, errors jsonb not null default '[]'
);
create index hackathons_date_idx on public.hackathons(start_date) where published;
create index hackathons_filters_idx on public.hackathons(city, format, registration_status) where published;
create index hackathons_topics_idx on public.hackathons using gin(topics);
create index hackathons_search_idx on public.hackathons using gin(to_tsvector('simple',coalesce(title,'') || ' ' || coalesce(organizer,'') || ' ' || coalesce(description,'')));
create index event_sources_url_idx on public.event_sources(url);
create function public.touch_updated_at() returns trigger language plpgsql set search_path=public as $$
begin new.updated_at = now(); return new; end $$;
create trigger hackathons_updated before update on public.hackathons for each row execute function public.touch_updated_at();
alter table public.hackathons enable row level security;
alter table public.sources enable row level security;
alter table public.event_sources enable row level security;
alter table public.discovery_runs enable row level security;
create policy published_events on public.hackathons for select to anon, authenticated using (published and verified);
revoke all on public.hackathons, public.sources, public.event_sources, public.discovery_runs from anon, authenticated;
grant select(id,title,organizer,description,city,format,start_date,end_date,registration_deadline,registration_url,official_source_url,age_min,age_max,age_restrictions,team_requirements,prize_info,has_prize,topics,registration_status,archived,last_verified_at) on public.hackathons to anon, authenticated;
grant all on public.hackathons,public.sources,public.event_sources,public.discovery_runs to service_role;
-- Security-invoker view preserves the base table RLS and hides stale open-registration claims.
create view public.public_hackathons with (security_invoker=true) as
select id,title,organizer,description,city,format,start_date,end_date,registration_deadline,registration_url,official_source_url,
 age_min,age_max,age_restrictions,team_requirements,prize_info,has_prize,topics,last_verified_at,
 (archived or coalesce(end_date,start_date) < (now() at time zone 'Asia/Baku')::date) as archived,
 case when coalesce(end_date,start_date) < (now() at time zone 'Asia/Baku')::date or registration_deadline < now() then 'closed'
 when last_verified_at < now() - interval '7 days' then 'unknown' else registration_status end as registration_status
from public.hackathons;
grant select on public.public_hackathons to anon, authenticated;
create function public.archive_expired() returns void language sql security definer set search_path=public as $$
 update public.hackathons set archived=true,registration_status='closed' where coalesce(end_date,start_date) < (now() at time zone 'Asia/Baku')::date;
$$;
revoke all on function public.archive_expired() from public, anon, authenticated;
grant execute on function public.archive_expired() to service_role;
commit;
