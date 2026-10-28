import { filterEvents, statistics } from '../shared/events.js';
import { answerQuestion } from './assistant.js';

const json = (data,status=200,headers={})=>new Response(JSON.stringify(data),{status,headers:{'Content-Type':'application/json; charset=utf-8','X-Content-Type-Options':'nosniff',...headers}});
const UUID = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
export async function loadEvents(env, fetcher=fetch) {
  if (!/^https:\/\/[a-z0-9-]+\.supabase\.co$/.test(env.SUPABASE_URL || '') || !env.SUPABASE_ANON_KEY) throw new Error('Database unavailable');
  const rows=[];
  for (let offset=0;offset<5000;offset+=500) {
    const url = new URL('/rest/v1/public_hackathons',env.SUPABASE_URL);
    url.search = new URLSearchParams({select:'*',order:'start_date.asc,id.asc',offset:String(offset),limit:'500'});
    const headers={apikey:env.SUPABASE_ANON_KEY};
    if(env.SUPABASE_ANON_KEY.startsWith('eyJ')) headers.Authorization=`Bearer ${env.SUPABASE_ANON_KEY}`;
    const r = await fetcher(url,{headers,signal:AbortSignal.timeout(10000)});
    if (!r.ok) throw new Error('Database unavailable');
    const batch = await r.json();
    if (!Array.isArray(batch)) throw new Error('Invalid database response');
    rows.push(...batch);
    if (batch.length < 500) return {events:rows,limited:false};
  }
  return {events:rows,limited:true};
}
async function cachedEvents(env,ctx,fetcher) {
  const cache = globalThis.caches?.default;
  const key = new Request('https://hackradar.internal/verified-events-v1');
  const hit = cache && await cache.match(key);
  if (hit) return hit.json();
  const data = await loadEvents(env,fetcher);
  if (cache) ctx.waitUntil(cache.put(key,json(data,200,{'Cache-Control':'public,max-age=300'})));
  return data;
}
function filters(params) {
  const f=Object.fromEntries(params);
  if (Object.keys(f).some(k=>!['q','city','format','topic','status','from','to','age','prize','archive'].includes(k))) throw new Error('Unknown filter');
  if (Object.values(f).some(v=>v.length>200) || (f.age && (!/^\d{1,3}$/.test(f.age) || +f.age>100))) throw new Error('Invalid filter');
  for (const field of ['from','to']) if (f[field] && (!/^\d{4}-\d{2}-\d{2}$/.test(f[field]) || !Number.isFinite(Date.parse(f[field])) || new Date(f[field]).toISOString().slice(0,10)!==f[field])) throw new Error('Invalid date');
  if (f.from && f.to && f.from>f.to) throw new Error('Invalid date range');
  for (const [k,allowed] of Object.entries({format:['onsite','online','hybrid'],status:['open','closed','unknown'],prize:['yes','no'],archive:['all','only']})) if (f[k] && !allowed.includes(f[k])) throw new Error('Invalid filter');
  return f;
}
async function readQuestion(request) {
  if (!request.headers.get('content-type')?.startsWith('application/json')) throw new Error('JSON required');
  const reader=request.body?.getReader();
  if (!reader) throw new Error('Body required');
  let size=0,chunks=[];
  try {
    while(true) { const {done,value}=await reader.read(); if(done) break; size+=value.length; if(size>4096) {await reader.cancel(); throw new Error('Body too large');} chunks.push(value); }
    const bytes=new Uint8Array(size); let offset=0; for(const c of chunks){bytes.set(c,offset);offset+=c.length;}
    const body=JSON.parse(new TextDecoder().decode(bytes));
    if (typeof body.question!=='string' || body.question.trim().length<3 || body.question.length>600 || /[\u0000-\u0008]/.test(body.question)) throw new Error('Invalid question');
    return body.question.trim();
  } finally { reader.releaseLock(); }
}
export async function handle(request,env,ctx={waitUntil(){}},fetcher=fetch) {
  const origin=request.headers.get('Origin');
  const allowed=env.ALLOWED_ORIGIN || 'http://localhost:5173';
  const headers={'Vary':'Origin','Access-Control-Allow-Origin':origin===allowed ? allowed : '', 'Access-Control-Allow-Methods':'GET,POST,OPTIONS','Access-Control-Allow-Headers':'Content-Type'};
  const respond=(data,status=200,extra={})=>json(data,status,{...headers,...extra});
  if (origin && origin!==allowed) return respond({error:'Origin icazəli deyil.'},403);
  if (request.method==='OPTIONS') return new Response(null,{status:204,headers});
  const url=new URL(request.url);
  if (url.pathname==='/api/health' && request.method==='GET') return respond({status:'ok',databaseConfigured:!!(env.SUPABASE_URL && env.SUPABASE_ANON_KEY),aiEnabled:env.GEMINI_ENABLED==='true'});
  const detail=url.pathname.match(/^\/api\/events\/([^/]+)$/);
  if (detail && !UUID.test(detail[1])) return respond({error:'Yanlış tədbir identifikatoru.'},400);
  if (!['/api/events','/api/stats','/api/assistant'].includes(url.pathname) && !detail) return respond({error:'Tapılmadı.'},404);
  if (request.method!==(url.pathname==='/api/assistant'?'POST':'GET')) return respond({error:'Metod icazəli deyil.'},405);
  let f,question;
  try { if(url.pathname==='/api/events') f=filters(url.searchParams); if(url.pathname==='/api/assistant') question=await readQuestion(request); }
  catch { return respond({error:url.pathname==='/api/events'?'Hakaton filtrləri yanlışdır. Parametrləri yoxlayın.':'Sorğu yanlışdır. Sual 3–600 simvol olmalıdır.'},400); }
  try {
    let quota;
    if(question) {
      if (!env.QUOTAS || !env.RATE_LIMIT_SALT) return respond({error:'Köməkçi hazırda əlçatan deyil.'},503);
      const ip=request.headers.get('CF-Connecting-IP') || 'local';
      const digest=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(env.RATE_LIMIT_SALT+ip));
      const ipHash=Array.from(new Uint8Array(digest)).map(n=>n.toString(16).padStart(2,'0')).join('');
      const stub=env.QUOTAS.get(env.QUOTAS.idFromName('anonymous-budget'));
      quota=await (await stub.fetch('https://quota/check',{method:'POST',body:JSON.stringify({ip:ipHash})})).json();
      if(!quota.allowed) return respond({error:'Sorğu limiti dolub. Bir qədər sonra yenidən yoxlayın.'},429,{'Retry-After':'60'});
    }
    const data=await cachedEvents(env,ctx,fetcher);
    if(question) {
      const active=filterEvents(data.events);
      const events=active.length ? active : data.events;
      const answer=await answerQuestion(question,events,{...env,GEMINI_ENABLED:quota.ai ? env.GEMINI_ENABLED : 'false'},fetcher);
      return respond({...answer,archivedOnly:!active.length});
    }
    if(detail) { const event=data.events.find(e=>e.id===detail[1]); return event ? respond({event}) : respond({error:'Tədbir tapılmadı.'},404); }
    if(url.pathname==='/api/stats') return respond({stats:statistics(data.events),limited:data.limited});
    return respond({events:filterEvents(data.events,f),stats:statistics(data.events),limited:data.limited},200,{'Cache-Control':'public,max-age=60'});
  } catch { return respond({error:'Məlumatlar hazırda yüklənmir. Bir qədər sonra yenidən yoxlayın.'},503); }
}
export default {fetch:handle};

// SQLite-backed Durable Object: atomic, cross-isolate limits, no IPs stored.
export class Quotas {
  constructor(state) {
    this.sql=state.storage.sql;
    this.sql.exec('CREATE TABLE IF NOT EXISTS counters (key TEXT PRIMARY KEY, n INTEGER NOT NULL, expires INTEGER NOT NULL)');
  }
  async fetch(request) {
    const {ip}=await request.json();
    if(!/^[a-f0-9]{64}$/.test(ip || '')) return json({allowed:false,ai:false});
    const now=Math.floor(Date.now()/1000),minute=Math.floor(now/60),day=Math.floor(now/86400);
    this.sql.exec('DELETE FROM counters WHERE expires < ?',now);
    const count=(key,expires)=>[...this.sql.exec('INSERT INTO counters(key,n,expires) VALUES (?,1,?) ON CONFLICT(key) DO UPDATE SET n=n+1 RETURNING n',key,expires)][0].n;
    const perMinute=count(`m:${ip}:${minute}`,now+60);
    if(perMinute>8) return json({allowed:false,ai:false});
    const perDay=count(`d:${ip}:${day}`,now+86400);
    const global=count(`global:${day}`,now+86400);
    return json({allowed:perDay<=40 && global<=2000,ai:perDay<=15 && global<=80});
  }
}
