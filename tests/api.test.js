import {test} from 'node:test';
import assert from 'node:assert/strict';
import {handle,loadEvents} from '../worker/index.js';
import {answerQuestion,groundedAnswer,selectFallback} from '../worker/assistant.js';
const e={id:'12345678-1234-1234-1234-123456789abc',title:'Fixture Hackathon',description:'Azerbaijan AI',city:'Bakı',start_date:new Date(Date.now()+30*86400000).toISOString().slice(0,10),age_restrictions:'18+',registration_status:'unknown',official_source_url:'https://university.example.org/hackathon',last_verified_at:new Date().toISOString()};
const env={SUPABASE_URL:'https://example.supabase.co',SUPABASE_ANON_KEY:'test-only',ALLOWED_ORIGIN:'https://frontend.example',RATE_LIMIT_SALT:'test-only',QUOTAS:{idFromName:x=>x,get:()=>({fetch:async()=>Response.json({allowed:true,ai:true})})}};
const database=async url=>{assert.equal(new URL(url).hostname,'example.supabase.co');return Response.json([e]);};
const req=(path,opts={})=>new Request('https://api.example'+path,opts);
const ctx={waitUntil(){}};
test('public events, stats, details and no write routes',async()=>{
 const r=await handle(req('/api/events?q=fixture'),env,ctx,database);assert.equal(r.status,200);assert.equal((await r.json()).events.length,1);
 assert.equal((await (await handle(req('/api/stats'),env,ctx,database)).json()).stats.total,1);
 assert.equal((await handle(req('/api/events/'+e.id),env,ctx,database)).status,200);
 assert.equal((await handle(req('/api/events/00000000-0000-0000-0000-000000000000'),env,ctx,database)).status,404);
 assert.equal((await handle(req('/api/events',{method:'POST'}),env,ctx,database)).status,405);
});
test('frontend archive GET returns active and archived events without assistant configuration',async()=>{
 const archived={...e,id:'87654321-1234-1234-1234-123456789abc',start_date:'2020-01-01',archived:true};
 let reads=0;
 const r=await handle(req('/api/events?archive=all',{headers:{Origin:env.ALLOWED_ORIGIN}}),{...env,QUOTAS:null,RATE_LIMIT_SALT:''},ctx,async()=>{reads++;return Response.json([e,archived]);});
 assert.equal(r.status,200);
 assert.equal(r.headers.get('Access-Control-Allow-Origin'),env.ALLOWED_ORIGIN);
 const data=await r.json();
 assert.deepEqual(data.events.map(event=>event.id),[e.id,archived.id]);
 assert.equal(data.stats.total,2);
 assert.equal(reads,1);
});
test('event filter errors are distinct from assistant question validation',async()=>{
 const unexpected=async()=>assert.fail('Invalid requests must not query the database');
 for(const path of ['/api/events?archive=invalid','/api/events?unexpected=all']) {
  const r=await handle(req(path),env,ctx,unexpected);
  assert.equal(r.status,400);
  assert.equal((await r.json()).error,'Hakaton filtrləri yanlışdır. Parametrləri yoxlayın.');
 }
 const r=await handle(req('/api/assistant',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question:'a'})}),env,ctx,unexpected);
 assert.equal(r.status,400);
 assert.equal((await r.json()).error,'Sorğu yanlışdır. Sual 3–600 simvol olmalıdır.');
});
test('filters, origins, dates and identifiers validated before DB access',async()=>{
 let called=false;const fetcher=()=>{called=true;throw new Error('unexpected');};
 for(const path of ['/api/events?age=-1','/api/events?format=sql','/api/events?from=2026-02-30','/api/events?from=2027-01-01&to=2026-01-01','/api/events/not-a-uuid'])assert.equal((await handle(req(path),env,ctx,fetcher)).status,400);
 assert.equal((await handle(req('/api/events',{headers:{Origin:'https://evil.example'}}),env,ctx,fetcher)).status,403);assert.equal(called,false);
});
test('database outage is explicit 503 and credentials never in responses',async()=>{
 const r=await handle(req('/api/events'),env,ctx,async()=>new Response('denied',{status:403}));assert.equal(r.status,503);assert.ok(!(await r.text()).includes('test-only'));
});
test('safe deterministic assistant supplies sourced facts',async()=>{
 const r=await handle(req('/api/assistant',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question:'Yaş şərtləri necədir?'})}),env,ctx,database);
 assert.equal(r.status,200);const answer=await r.json();assert.equal(answer.mode,'fallback');assert.match(answer.answer,/18\+/);assert.match(answer.answer,/təsdiqlənməyib/);assert.equal(answer.sources[0].url,e.official_source_url);
 assert.equal(groundedAnswer([]).sources.length,0);
});
test('anonymous quota and bounded request body enforced',async()=>{
 const blocked={...env,QUOTAS:{...env.QUOTAS,get:()=>({fetch:async()=>Response.json({allowed:false})})}};
 const opts={method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question:'Hakaton tap'})};
 assert.equal((await handle(req('/api/assistant',opts),blocked,ctx,database)).status,429);
 for(const question of ['a','x'.repeat(601),'x'.repeat(5000)])assert.equal((await handle(req('/api/assistant',{...opts,body:JSON.stringify({question})}),env,ctx,database)).status,400);
 assert.equal((await handle(req('/api/assistant',opts),{...env,QUOTAS:null},ctx,database)).status,503);
});
test('Gemini can only select known records; quota failures fall back',async()=>{
 const ai={GEMINI_ENABLED:'true',GEMINI_API_KEY:'test-secret'};
 const reply=result=>async()=>Response.json({candidates:[{content:{parts:[{text:JSON.stringify(result)}]}}]});
 assert.equal((await answerQuestion('Müqayisə et',[e],ai,reply({event_ids:[e.id],focus:'comparison'}))).mode,'gemini');
 const fake=await answerQuestion('Test',[e],ai,reply({event_ids:['fabricated'],focus:'general'}));assert.equal(fake.mode,'fallback');assert.ok(!fake.answer.includes('fabricated'));
 assert.equal((await answerQuestion('Test',[e],ai,async()=>new Response('',{status:429}))).mode,'fallback');
});
test('database reads are paginated rather than silently cut at Supabase default',async()=>{
 let calls=0;const r=await loadEvents(env,async url=>{calls++;const offset=+new URL(url).searchParams.get('offset');return Response.json(offset===0?Array(500).fill(e):[e]);});assert.equal(calls,2);assert.equal(r.events.length,501);assert.equal(r.limited,false);
});

test('fallback respects explicit open-registration and age questions',()=>{assert.equal(selectFallback('Qeydiyyat açıqdır?', [e]).length,0);assert.equal(selectFallback('17 yaşım var',[{...e,age_min:18}]).length,0);});
