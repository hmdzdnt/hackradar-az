import { groundedAnswer, selectFallback } from '../worker/assistant.js';
const base = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/,'');
export const snapshotMode = !base;
async function request(path, options) {
  const r = await fetch(base+path,{...options,signal:AbortSignal.timeout(15000)});
  const data = await r.json();
  if (!r.ok) throw new Error(data.error || 'Məlumatlar yüklənmədi.');
  return data;
}
export async function getEvents() {
  const data = await request(base ? '/api/events?archive=all' : '/events.json');
  if(!Array.isArray(data.events)) throw new Error('Məlumat formatı düzgün deyil.');
  return data;
}
export async function askAssistant(question, events) {
  if (!base) return {...groundedAnswer(selectFallback(question,events)),archivedOnly:events.length>0 && events.every(e=>(e.end_date||e.start_date)<new Date().toISOString().slice(0,10))};
  return request('/api/assistant',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question})});
}
