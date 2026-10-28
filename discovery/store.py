import asyncio
from datetime import datetime, timezone
import os
import re
import httpx
from .extract import duplicate


class Store:
    """PostgREST with server-only service key. Never interpolates SQL."""
    def __init__(self):
        url = os.environ.get('SUPABASE_URL','').rstrip('/')
        key = os.environ.get('SUPABASE_SERVICE_ROLE_KEY','')
        if not re.fullmatch(r'https://[a-z0-9-]+\.supabase\.co', url) or not key:
            raise ValueError('Configure SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY')
        headers={'apikey':key,'Prefer':'return=representation'}
        if key.startswith('eyJ'):
            headers['Authorization']='Bearer '+key
        self.client = httpx.AsyncClient(base_url=url+'/rest/v1/',timeout=20,headers=headers)

    async def request(self, method, path, **kwargs):
        for attempt in range(3):
            try:
                r = await self.client.request(method,path,**kwargs)
                r.raise_for_status()
                return r.json() if r.content else None
            except (httpx.TimeoutException,httpx.NetworkError,httpx.HTTPStatusError) as e:
                if attempt == 2 or (isinstance(e,httpx.HTTPStatusError) and e.response.status_code < 500):
                    raise RuntimeError(f'Database request failed: {type(e).__name__}') from None
                await asyncio.sleep(2**attempt)

    async def source(self, source):
        payload = {k:source[k] for k in ('name','url','kind','trusted')}
        rows = await self.request('POST','sources',params={'on_conflict':'url'},json=payload,headers={'Prefer':'resolution=merge-duplicates,return=representation'})
        return rows[0]['id']

    async def save(self, event, source_id, content_hash):
        # URL identity survives corrections to title or date. Secondary matching merges syndication.
        links = await self.request('GET','event_sources',params={'url':'eq.'+event['official_source_url'],'select':'event_id','limit':'1'})
        existing_id = links[0]['event_id'] if links else None
        if not existing_id:
            params = {'select':'id,title,start_date,fingerprint,official_source_url','limit':'1000'}
            if event.get('start_date'):
                params['start_date'] = 'eq.'+event['start_date']
            rows = await self.request('GET','hackathons',params=params)
            match = next((row for row in rows if duplicate(event,row)),None)
            existing_id = match['id'] if match else None
        if existing_id:
            rows = await self.request('PATCH','hackathons',params={'id':'eq.'+existing_id},json=event)
        else:
            rows = await self.request('POST','hackathons',params={'on_conflict':'fingerprint'},json=event,headers={'Prefer':'resolution=merge-duplicates,return=representation'})
        event_id = rows[0]['id']
        await self.request('POST','event_sources',params={'on_conflict':'event_id,url'},json={'event_id':event_id,'source_id':source_id,'url':event['official_source_url'],'content_hash':content_hash,'last_seen_at':datetime.now(timezone.utc).isoformat()},headers={'Prefer':'resolution=merge-duplicates,return=representation'})
        return event_id

    async def close(self):
        await self.client.aclose()
