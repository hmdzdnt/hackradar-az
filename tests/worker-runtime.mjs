import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { Miniflare, convertV4MiniflareOptions } from 'miniflare';
const data=JSON.parse(await readFile(new URL('../public/events.json',import.meta.url),'utf8'));
const mf=new Miniflare(convertV4MiniflareOptions({workers:[{
  name:'api',outboundService:async request=>{assert.equal(new URL(request.url).hostname,'runtime-test.supabase.co');return Response.json(data.events);},modules:true,scriptPath:'artifacts/worker/index.js',compatibilityDate:'2026-10-01',
  durableObjects:{QUOTAS:{className:'Quotas',useSQLite:true}},
  bindings:{SUPABASE_URL:'https://runtime-test.supabase.co',SUPABASE_ANON_KEY:'sb_publishable_test',RATE_LIMIT_SALT:'runtime-test-only',ALLOWED_ORIGIN:'https://frontend.example',GEMINI_ENABLED:'false'},
}]}));
try {
 const health=await mf.dispatchFetch('https://api.example/api/health');assert.equal(health.status,200);
 const r=await mf.dispatchFetch('https://api.example/api/events?archive=all');assert.equal(r.status,200);
 const result=await r.json();assert.equal(result.events.length,data.events.length);
 const detail=await mf.dispatchFetch('https://api.example/api/events/'+data.events[0].id);assert.equal(detail.status,200);
 for(let i=0;i<9;i++) {
  const res=await mf.dispatchFetch('https://api.example/api/assistant',{method:'POST',headers:{'Content-Type':'application/json','CF-Connecting-IP':'203.0.113.12'},body:JSON.stringify({question:'Hansı hakatonlar var?'})});
  assert.equal(res.status,i<8?200:429,`request ${i+1}`);
  if(i===0) {const answer=await res.json();assert.equal(answer.mode,'fallback');assert.ok(answer.sources.length>0);}
 }
 console.log('Worker runtime: real-source data read, details, grounded fallback and SQLite Durable Object 8/min quota passed.');
} finally {await mf.dispose();}
