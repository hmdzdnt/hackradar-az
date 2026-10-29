// Local embedded PostgreSQL only. This script never connects to Supabase.
import { PGlite } from '@electric-sql/pglite';
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';

const db = new PGlite();
const day = '2027-01-01';
const start = `${day}T10:00:00+04:00`;
const end = `${day}T18:00:00+04:00`;
const cases = [
  ['absent', {}, null, null],
  ['json-null', null, null, null],
  ['root-array', ['timing'], null, null],
  ['null-timing', {timing:null}, null, null],
  ['scalar-timing', {timing:'bad'}, null, null],
  ['array-timing', {timing:[]}, null, null],
  ['null-values', {timing:{start_at:null,end_at:null}}, null, null],
  ['empty', {timing:{start_at:'',end_at:' '}}, null, null],
  ['malformed', {timing:{start_at:'not-a-timestamp',end_at:'2027-02-30T18:00:00+04:00'}}, null, null],
  ['wrong-types', {timing:{start_at:{value:start},end_at:123}}, null, null],
  ['array-bool-values', {timing:{start_at:[start],end_at:true}}, null, null],
  ['date-only', {timing:{start_at:day,end_at:day}}, null, null],
  ['timezone-missing', {timing:{start_at:`${day}T10:00:00`,end_at:`${day}T18:00:00`}}, null, null],
  ['special-values', {timing:{start_at:'now',end_at:'infinity'}}, null, null],
  ['invalid-offset', {timing:{start_at:`${day}T10:00:00+99:99`,end_at:null}}, null, null],
  ['reverse', {timing:{start_at:end,end_at:start}}, null, null],
  ['equal', {timing:{start_at:start,end_at:start}}, null, null],
  ['different-days', {timing:{start_at:'2028-01-01T10:00:00+04:00',end_at:'2028-01-01T18:00:00+04:00'}}, null, null],
  ['valid-pair', {timing:{start_at:start,end_at:end}}, start, end],
  ['valid-start', {timing:{start_at:start,end_at:'bad'}}, start, null],
  ['valid-end', {timing:{start_at:null,end_at:end}}, null, end],
  ['utc', {timing:{start_at:`${day}T06:00:00Z`,end_at:`${day}T14:00:00Z`}}, start, end],
  ['utc-baku-rollover', {timing:{start_at:'2026-12-31T21:00:00Z',end_at:`${day}T02:00:00Z`}}, `${day}T01:00:00+04:00`, `${day}T06:00:00+04:00`],
  ['whitespace', {timing:{start_at:` ${start} `,end_at:end}}, start, end],
];
try {
  await db.exec("SET TIME ZONE 'America/New_York'"); // Backfill must not depend on the SQL Editor's session timezone.
  await db.exec('CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;');
  await db.exec(await readFile(new URL('../supabase/migrations/001_initial.sql',import.meta.url),'utf8'));
  for (const [name,evidence] of cases) {
    await db.query(`INSERT INTO public.hackathons (fingerprint,title,start_date,end_date,official_source_url,evidence,updated_at)
      VALUES ($1,$2,$3,$3,'https://official.example.org/event',$4::jsonb,'2000-01-01T00:00:00Z')`,[name,`Private fixture ${name}`,day,JSON.stringify(evidence)]);
  }
  await db.query(`INSERT INTO public.hackathons (fingerprint,title,start_date,end_date,official_source_url,verified,published,last_verified_at)
    VALUES ('public','Published fixture',$1,$1,'https://official.example.org/public',true,true,now()),
           ('verified-private','Verified unpublished fixture',$1,$1,'https://official.example.org/private',true,false,now())`,[day]);
  const snapshot = async () => (await db.query(`SELECT to_jsonb(h)-ARRAY['updated_at','start_at','end_at','event_timezone','announcement_url','location'] AS original_fields FROM public.hackathons h ORDER BY fingerprint`)).rows;
  const before = await snapshot();
  await db.exec('SET ROLE anon');
  assert.deepEqual((await db.query('SELECT title FROM public.public_hackathons')).rows,[{title:'Published fixture'}],'Migration 001 policy protects unpublished records');
  await db.exec('RESET ROLE');
  await db.exec(await readFile(new URL('../supabase/migrations/002_discovery_quality.sql',import.meta.url),'utf8'));
  assert.deepEqual(await snapshot(),before,'Existing record fields, evidence and row count are preserved');
  for (const [name,,expectedStart,expectedEnd] of cases) {
    const row=(await db.query(`SELECT start_at IS NOT DISTINCT FROM $2::timestamptz AS start_ok,
      end_at IS NOT DISTINCT FROM $3::timestamptz AS end_ok, updated_at='2000-01-01T00:00:00Z'::timestamptz AS untouched
      FROM public.hackathons WHERE fingerprint=$1`,[name,expectedStart,expectedEnd])).rows[0];
    assert.equal(row.start_ok,true,`${name}: start timestamp`);
    assert.equal(row.end_ok,true,`${name}: end timestamp`);
    assert.equal(row.untouched,expectedStart===null && expectedEnd===null,`${name}: invalid/empty evidence must not update the row`);
  }
  const options=(await db.query("SELECT reloptions FROM pg_class WHERE oid='public.public_hackathons'::regclass")).rows[0].reloptions;
  assert.ok(options.includes('security_invoker=true'));
  // Simulate policy drift: PostgreSQL normally ORs permissive policies together.
  await db.exec('CREATE POLICY accidental_broad_read ON public.hackathons FOR SELECT TO anon,authenticated USING (true)');
  for (const role of ['anon','authenticated']) {
    await db.exec(`SET ROLE ${role}`);
    assert.deepEqual((await db.query('SELECT title FROM public.public_hackathons')).rows,[{title:'Published fixture'}],`${role}: view cannot expose unpublished rows`);
    assert.deepEqual((await db.query('SELECT title FROM public.hackathons')).rows,[{title:'Published fixture'}],`${role}: direct table reads also preserve RLS`);
    assert.equal((await db.query("SELECT count(*)::int AS n FROM public.public_hackathons WHERE title LIKE 'Private%' OR title LIKE 'Verified unpublished%'")).rows[0].n,0);
    await assert.rejects(db.query('SELECT published,verified FROM public.hackathons'),`${role}: private flags need no new grants`);
    await assert.rejects(db.query('SELECT evidence FROM public.hackathons'),`${role}: evidence remains private`);
    await assert.rejects(db.query('SELECT * FROM public.discovery_runs'),`${role}: run summaries remain private`);
    await assert.rejects(db.query('SELECT public.archive_expired()'),`${role}: security-definer archival RPC cannot be invoked`);
    await assert.rejects(db.query("UPDATE public.hackathons SET title='tampered'"),`${role}: writes remain denied`);
    await db.exec('RESET ROLE');
  }
  assert.equal((await db.query('SELECT count(*)::int AS n FROM public.hackathons')).rows[0].n,cases.length+2,'Owner still sees all retained records');
  assert.equal((await db.query("SELECT count(*)::int AS n FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE p.proname='hackradar_evidence_timestamp' AND n.nspname LIKE 'pg_temp_%'")).rows[0].n,0,'Temporary parsing helper is removed');
  console.log(`Migration safety: ${cases.length} evidence cases, retained records, security-invoker view, anon/auth RLS under broad policy, private fields and RPC/write denial passed.`);
} finally { await db.close(); }
