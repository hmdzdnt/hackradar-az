-- MANUAL DEPLOYMENT: additive migration. Apply after review; no historical rows deleted.
begin;
alter table public.hackathons add column start_at timestamptz, add column end_at timestamptz,
 add column event_timezone text not null default 'Asia/Baku', add column announcement_url text,
 add column location text;
alter table public.hackathons add constraint valid_event_times check (start_at is null or end_at is null or end_at > start_at),
 add constraint announcement_https check (announcement_url is null or announcement_url ~ '^https://');
alter table public.discovery_runs add column summary jsonb not null default '{}';
create index hackathons_end_at_idx on public.hackathons(end_at) where published;

create function public.event_lifecycle(p_start_date date,p_end_date date,p_start_at timestamptz,p_end_at timestamptz,p_now timestamptz default now())
returns text language sql stable set search_path=public as $$
 select case
 when coalesce(p_end_at,((coalesce(p_end_date,p_start_date)+1)::timestamp at time zone 'Asia/Baku')) <= p_now then 'archived'
 when coalesce(p_start_at,(p_start_date::timestamp at time zone 'Asia/Baku')) <= p_now then 'ongoing'
 when p_start_date is not null or p_start_at is not null then 'upcoming' else 'unknown' end;
$$;
-- Only explicit ISO timestamps with an offset are eligible for backfill.
-- JSON nulls, wrong types, malformed/calendar-invalid values and ambiguous local
-- times stay null. Use a session-local parser; expose no public parsing RPC.
create function pg_temp.hackradar_evidence_timestamp(p_value jsonb)
returns timestamptz language plpgsql set search_path=pg_catalog as $$
declare
 raw_value text;
 parsed_value timestamptz;
begin
 if jsonb_typeof(p_value) is distinct from 'string' then return null; end if;
 raw_value=btrim(p_value #>> '{}');
 if raw_value !~* '^[0-9]{4}-[0-9]{2}-[0-9]{2}T([01][0-9]|2[0-3]):[0-5][0-9](:[0-5][0-9](\.[0-9]{1,6})?)?(Z|[+-][0-9]{2}:[0-9]{2})$' then
  return null;
 end if;
 begin
  parsed_value=raw_value::timestamptz;
 exception when sqlstate '22007' or sqlstate '22008' or sqlstate '22009' then
  return null;
 end;
 if not isfinite(parsed_value) then return null; end if;
 return parsed_value;
end $$;

with parsed as materialized (
 select id,start_date,end_date,
  pg_temp.hackradar_evidence_timestamp(evidence->'timing'->'start_at') as parsed_start,
  pg_temp.hackradar_evidence_timestamp(evidence->'timing'->'end_at') as parsed_end
 from public.hackathons
 where jsonb_typeof(evidence)='object' and jsonb_typeof(evidence->'timing')='object'
), aligned as (
 select id,
  case when start_date is null or (parsed_start at time zone 'Asia/Baku')::date=start_date then parsed_start end as valid_start,
  case when end_date is null or (parsed_end at time zone 'Asia/Baku')::date=end_date then parsed_end end as valid_end
 from parsed
 -- Contradictory ranges are left for review rather than aborting the migration.
 where parsed_start is null or parsed_end is null or parsed_end>parsed_start
)
update public.hackathons h set start_at=a.valid_start,end_at=a.valid_end
from aligned a
where h.id=a.id and (a.valid_start is not null or a.valid_end is not null);

drop function pg_temp.hackradar_evidence_timestamp(jsonb);

-- Keep invoker RLS effective, including if another permissive SELECT policy is
-- accidentally added later. No new permissions on evidence or private flags.
alter table public.hackathons enable row level security;
create policy published_events_guard on public.hackathons as restrictive
 for select to anon,authenticated using (published and verified);

grant select(start_at,end_at,event_timezone,announcement_url,location) on public.hackathons to anon,authenticated;
-- Preserve all existing view columns in their original order, append new fields only.
create or replace view public.public_hackathons with (security_invoker=true) as
select id,title,organizer,description,city,format,start_date,end_date,registration_deadline,registration_url,official_source_url,
 age_min,age_max,age_restrictions,team_requirements,prize_info,has_prize,topics,last_verified_at,
 (public.event_lifecycle(start_date,end_date,start_at,end_at)='archived') as archived,
 case when public.event_lifecycle(start_date,end_date,start_at,end_at)='archived' or registration_deadline < now() then 'closed'
 when last_verified_at < now()-interval '7 days' then 'unknown' else registration_status end as registration_status,
 start_at,end_at,event_timezone,announcement_url,location,
 public.event_lifecycle(start_date,end_date,start_at,end_at) as lifecycle
from public.hackathons;
grant select on public.public_hackathons to anon,authenticated;

create or replace function public.archive_expired() returns void language sql security definer set search_path=public as $$
 update public.hackathons set archived=true,registration_status='closed'
 where public.event_lifecycle(start_date,end_date,start_at,end_at)='archived' and (not archived or registration_status<>'closed');
$$;
-- Defense in depth: updates to existing historical rows remain allowed.
create function public.reject_expired_new_event() returns trigger language plpgsql set search_path=public as $$
begin
 if public.event_lifecycle(new.start_date,new.end_date,new.start_at,new.end_at)='archived' then
  raise exception 'New discovery record has already ended' using errcode='23514';
 end if;
 return new;
end $$;
create trigger no_expired_new_events before insert on public.hackathons for each row execute function public.reject_expired_new_event();
revoke all on function public.archive_expired() from public,anon,authenticated;
grant execute on function public.archive_expired() to service_role;
commit;
