import {test} from 'node:test';
import assert from 'node:assert/strict';
import {filterEvents,registration,statistics,monthEvents,safeHref,bakuToday} from '../shared/events.js';
const now=new Date('2026-10-28T20:30:00Z');
const event={id:'test-fixture',title:'Süni intellekt hakatonu',organizer:'Test Universiteti',description:'Məlumat təhlili',city:'Bakı',format:'onsite',topics:['Enerji'],start_date:'2026-11-21',end_date:'2026-11-22',age_min:18,age_max:30,has_prize:true,registration_status:'open',last_verified_at:now.toISOString()};
test('search covers all requested fields and Azerbaijani case',()=>{
 for(const q of ['SÜNİ','Test Universiteti','Məlumat','ENERJİ','BAKI']) assert.equal(filterEvents([event],{q},now).length,1,q);
 assert.equal(filterEvents([event],{q:'unrelated'},now).length,0);
});
test('combined filters, age and unknown fields',()=>{
 assert.equal(filterEvents([event],{city:'Bakı',format:'onsite',topic:'Enerji',status:'open',age:'18',prize:'yes',from:'2026-11-22',to:'2026-11-25'},now).length,1);
 for(const f of [{age:'17'},{city:'Gəncə'},{format:'online'},{status:'closed'},{prize:'no'},{to:'2026-11-20'},{from:'2026-11-23'}]) assert.equal(filterEvents([event],f,now).length,0);
 assert.equal(filterEvents([{...event,age_min:null,age_max:null}],{age:'18'},now).length,0);
});
test('registration is never inferred open and stale claims expire',()=>{
 assert.equal(registration({...event,registration_status:'unknown'},now),'unknown');
 assert.equal(registration({...event,last_verified_at:'2026-10-01'},now),'unknown');
 assert.equal(registration({...event,registration_deadline:'2026-10-01'},now),'closed');
});
test('archive, stats, calendar overlap and Baku midnight',()=>{
 const past={...event,id:'past',start_date:'2026-09-30',end_date:'2026-10-02'};
 assert.equal(filterEvents([event,past],{},now).length,1);
 assert.equal(filterEvents([event,past],{archive:'all'},now).length,2);
 assert.equal(filterEvents([event,past],{archive:'only'},now)[0].id,'past');
 assert.equal(monthEvents([past],2026,9).length,1);
 assert.deepEqual(statistics([event,past],now),{total:2,upcoming:1,open:1,organizers:1,cities:1});
 assert.equal(bakuToday(now),'2026-10-29');
});
test('unsafe hyperlinks cannot become executable URLs',()=>{for(const u of ['javascript:alert(1)','data:text/html,<script>','http://foo.test','https://user@foo.test'])assert.equal(safeHref(u),null);assert.equal(safeHref('https://example.org/'),'https://example.org/');});
