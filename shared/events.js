export const fold = value => String(value ?? '').normalize('NFKC').toLocaleLowerCase('az-AZ');
export const bakuToday = (now = new Date()) => new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Baku', year: 'numeric', month: '2-digit', day: '2-digit' }).format(now);
export function eventLifecycle(event, now = new Date()) {
  const boundary=(instant,day,end=false)=> {
    if (instant && Number.isFinite(Date.parse(instant))) return Date.parse(instant);
    if (!day || !/^\d{4}-\d{2}-\d{2}$/.test(day)) return null;
    const midnight=Date.parse(day+'T00:00:00+04:00');
    return Number.isFinite(midnight) ? midnight+(end?86400000:0) : null;
  };
  const end=boundary(event.end_at,event.end_date||event.start_date,true);
  const start=boundary(event.start_at,event.start_date);
  if (end!=null && end<=now.getTime()) return 'archived';
  if (start!=null && start<=now.getTime()) return 'ongoing';
  if (start!=null) return 'upcoming';
  return event.archived ? 'archived' : 'unknown';
}
export function registration(event, now = new Date()) {
  if (eventLifecycle(event,now)==='archived' || (event.registration_deadline && new Date(event.registration_deadline) < now)) return 'closed';
  if (!event.last_verified_at || now - new Date(event.last_verified_at) > 7 * 86400000) return 'unknown';
  return ['open', 'closed'].includes(event.registration_status) ? event.registration_status : 'unknown';
}
export function filterEvents(events, f = {}, now = new Date()) {
  return events.filter(e => {
    const text = fold([e.title,e.organizer,e.description,e.city,...(e.topics || [])].join(' '));
    if (f.q && !fold(f.q).split(/\s+/).filter(Boolean).every(word => text.includes(word))) return false;
    if (f.city && e.city !== f.city) return false;
    if (f.format && e.format !== f.format) return false;
    if (f.topic && !e.topics?.includes(f.topic)) return false;
    if (f.status && registration(e,now) !== f.status) return false;
    if (f.from && (!e.start_date || (e.end_date || e.start_date) < f.from)) return false;
    if (f.to && (!e.start_date || e.start_date > f.to)) return false;
    if (f.age !== '' && f.age != null) {
      const age = Number(f.age);
      if (!Number.isInteger(age) || age < 0 || age > 100 || (e.age_min == null && e.age_max == null)) return false;
      if ((e.age_min != null && age < e.age_min) || (e.age_max != null && age > e.age_max)) return false;
    }
    if (f.prize === 'yes' && e.has_prize !== true) return false;
    if (f.prize === 'no' && e.has_prize !== false) return false;
    const life=eventLifecycle(e,now);
    if (f.lifecycle && f.lifecycle!==life) return false;
    if (f.archive !== 'all' && f.archive !== 'only' && !f.lifecycle && life==='archived') return false;
    if (f.archive === 'only' && life!=='archived') return false;
    return true;
  });
}
export function statistics(events, now = new Date()) {
  const active = filterEvents(events,{},now);
  return { total: events.length, upcoming: active.length, open: active.filter(e => registration(e,now) === 'open').length, organizers: new Set(events.map(e=>e.organizer).filter(Boolean)).size, cities: new Set(events.map(e=>e.city).filter(Boolean)).size };
}
export function monthEvents(events, year, month) {
  const first = `${year}-${String(month+1).padStart(2,'0')}-01`;
  const last = `${year}-${String(month+1).padStart(2,'0')}-${new Date(year,month+1,0).getDate()}`;
  return events.filter(e => e.start_date && e.start_date <= last && (e.end_date || e.start_date) >= first);
}
export function safeHref(value) {
  try { const u = new URL(value); return u.protocol === 'https:' && !u.username && !u.password ? u.href : null; } catch { return null; }
}
