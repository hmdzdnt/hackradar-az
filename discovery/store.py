import asyncio
from datetime import datetime,timedelta,timezone
import os
import re
import httpx
from .extract import duplicate
from .dates import lifecycle,iso_day

LEGACY_FIELDS=set('fingerprint title organizer description city format start_date end_date registration_deadline registration_url official_source_url age_min age_max age_restrictions team_requirements prize_info has_prize topics registration_status registration_evidence verified published archived evidence last_verified_at'.split())
EXTRA_FIELDS=set('start_at end_at event_timezone announcement_url location'.split())

class DatabaseError(RuntimeError):
    def __init__(self,method,path,status=None,code=None):
        self.status=status;self.code=code
        # No response body, credentials, query strings or provider URL in exceptions/logs.
        super().__init__(f'Database {method} {path.split("?")[0]} failed (HTTP {status or "network"}, code {code or "unknown"})')


class Store:
    def __init__(self):
        url=os.environ.get('SUPABASE_URL','').rstrip('/')
        key=os.environ.get('SUPABASE_SERVICE_ROLE_KEY','')
        if not re.fullmatch(r'https://[a-z0-9-]+\.supabase\.co',url) or not key:raise ValueError('Configure SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY')
        headers={'apikey':key,'Prefer':'return=representation'}
        if key.startswith('eyJ'):headers['Authorization']='Bearer '+key
        self.client=httpx.AsyncClient(base_url=url+'/rest/v1/',timeout=20,headers=headers)
        self.extended_schema=False

    async def request(self,method,path,**kwargs):
        for attempt in range(3):
            try:
                r=await self.client.request(method,path,**kwargs)
                r.raise_for_status()
                return r.json() if r.content else None
            except (httpx.TimeoutException,httpx.NetworkError,httpx.HTTPStatusError) as e:
                status=e.response.status_code if isinstance(e,httpx.HTTPStatusError) else None
                code=None
                if status:
                    try:
                        candidate=e.response.json().get('code','')
                        if isinstance(candidate,str) and re.fullmatch(r'[A-Z0-9]+',candidate):code=candidate
                    except (ValueError,AttributeError):pass
                if attempt==2 or (status and status<500):raise DatabaseError(method,path,status,code) from None
                await asyncio.sleep(2**attempt)

    async def detect_schema(self):
        try:
            await self.request('GET','public_hackathons',params={'select':'start_at,end_at,event_timezone,announcement_url,location,lifecycle','limit':'0'})
            self.extended_schema=True
        except DatabaseError as e:
            if e.status==400 and e.code in ('42703','PGRST204'):self.extended_schema=False
            else:raise
        return self.extended_schema

    async def source(self,source):
        payload={k:source[k] for k in ('name','url','kind','trusted')}
        payload['enabled']=source.get('enabled',True)
        rows=await self.request('POST','sources',params={'on_conflict':'url'},json=payload,headers={'Prefer':'resolution=merge-duplicates,return=representation'})
        return rows[0]['id']

    async def find(self,event):
        links=await self.request('GET','event_sources',params={'url':'eq.'+event['official_source_url'],'select':'event_id,content_hash','limit':'30'})
        for link in links:
            rows=await self.request('GET','hackathons',params={'id':'eq.'+link['event_id'],'select':'*','limit':'1'})
            if rows and duplicate(event,rows[0]):return rows[0],link.get('content_hash')
        params={'select':'*','limit':'500'}
        if iso_day(event.get('start_date')):
            day=datetime.fromisoformat(event['start_date'])
            params['and']=f'(start_date.gte.{(day-timedelta(days=90)).date()},start_date.lte.{(day+timedelta(days=90)).date()})'
        else:params['fingerprint']='eq.'+event['fingerprint']
        rows=await self.request('GET','hackathons',params=params)
        return next(((row,None) for row in rows if duplicate(event,row)),(None,None))

    async def link(self,event_id,source_id,url,content_hash):
        await self.request('POST','event_sources',params={'on_conflict':'event_id,url'},json={'event_id':event_id,'source_id':source_id,'url':url,'content_hash':content_hash,'last_seen_at':datetime.now(timezone.utc).isoformat()},headers={'Prefer':'resolution=merge-duplicates,return=representation'})

    async def save(self,event,source_id,content_hash,announcement_source_id=None):
        existing,_old_hash=await self.find(event)
        # This guard is independent of extraction/verification and runs immediately before writing.
        expired=lifecycle(event)=='archived'
        if expired and not existing and not (event.get('end_date') or event.get('end_at')):
            # Past start plus unknown end is ambiguous, not proof of expiry. Keep it in the review artifact only.
            return {'status':'quarantined','id':None,'created':False}
        if expired:
            if existing:
                await self.request('PATCH','hackathons',params={'id':'eq.'+existing['id']},json={'archived':True,'registration_status':'closed'})
                await self.link(existing['id'],source_id,event['official_source_url'],content_hash)
            return {'status':'expired','id':existing['id'] if existing else None,'created':False}
        decision=event.get('evidence',{}).get('review',{}).get('decision')
        if decision in ('rejected','expired'):return {'status':decision,'id':None,'created':False}
        if existing and existing.get('published') and not event.get('published'):
            # An incomplete scrape/social repost must never erase a verified official record.
            await self.link(existing['id'],source_id,event['official_source_url'],content_hash)
            return {'status':'duplicate','id':existing['id'],'created':False}
        payload={k:v for k,v in event.items() if k in LEGACY_FIELDS or self.extended_schema and k in EXTRA_FIELDS}
        if existing:
            # Missing facts in a new page do not erase previously verified non-null facts.
            for k,v in list(payload.items()):
                if v is None and existing.get(k) is not None and k not in ('registration_evidence','last_verified_at'):payload[k]=existing[k]
            rows=await self.request('PATCH','hackathons',params={'id':'eq.'+existing['id']},json=payload)
        else:
            rows=await self.request('POST','hackathons',params={'on_conflict':'fingerprint'},json=payload,headers={'Prefer':'resolution=merge-duplicates,return=representation'})
        unchanged=bool(existing) and all(existing.get(k)==v for k,v in payload.items() if k not in ('evidence','last_verified_at'))
        event_id=rows[0]['id']
        await self.link(event_id,source_id,event['official_source_url'],content_hash)
        if event.get('announcement_url') and event['announcement_url']!=event['official_source_url']:
            await self.link(event_id,announcement_source_id or source_id,event['announcement_url'],content_hash)
        return {'status':'quarantined' if not event.get('published') else 'duplicate' if unchanged else 'accepted','id':event_id,'created':not existing}

    async def close(self):await self.client.aclose()
