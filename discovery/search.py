"""Opt-in official search API. No search-result HTML scraping or paid fallback."""
import os
from urllib.parse import urlparse
import httpx
from .connectors import SEARCH_QUERIES
from .urls import canonical_url

# Public page/API support is not the same as permission to crawl an entire platform.
PLATFORM_POLICIES={
 'instagram.com':'restricted: no approved API/feed configured',
 'facebook.com':'restricted: no approved API/feed configured',
 'linkedin.com':'restricted: no approved API/feed configured',
 't.me':'manual review: public channel URL and access policy required',
 'x.com':'restricted: no approved API/feed configured',
 'twitter.com':'restricted: no approved API/feed configured',
 'tiktok.com':'restricted: no approved API/feed configured',
 'youtube.com':'official API credentials/usage policy not configured',
 'devpost.com':'public event pages only after source/terms review',
 'eventbrite.com':'public event pages or official API only after source/terms review',
 'lu.ma':'public event pages only after source/terms review',
 'luma.com':'public event pages only after source/terms review',
}


def queries_for_slot(slot,limit=4):
    return [SEARCH_QUERIES[(slot*limit+i)%len(SEARCH_QUERIES)] for i in range(min(limit,4))]


async def search_links(slot,client=None):
    if os.environ.get('DISCOVERY_SEARCH_ENABLED')!='true':return [],{'status':'disabled','reason':'Explicit free-tier opt-in and API key required'}
    key=os.environ.get('DISCOVERY_SEARCH_API_KEY','')
    if not key:return [],{'status':'unavailable','reason':'DISCOVERY_SEARCH_API_KEY is missing'}
    owned=client is None
    client=client or httpx.AsyncClient(timeout=15,follow_redirects=False)
    links=[];completed=0;failures=[]
    try:
        for query in queries_for_slot(slot):
            try:
                r=await client.get('https://api.search.brave.com/res/v1/web/search',params={'q':query,'count':5,'safesearch':'strict'},headers={'X-Subscription-Token':key,'Accept':'application/json'})
                if r.status_code in (401,403,429):
                    failures.append({'http_status':r.status_code});break  # No retries or quota bypass.
                r.raise_for_status();completed+=1
                for item in r.json().get('web',{}).get('results',[]):
                    url=canonical_url(item.get('url'))
                    if url and url not in links:links.append(url)
            except (httpx.HTTPError,ValueError,AttributeError):failures.append({'error':'search_request_failed'})
    finally:
        if owned:await client.aclose()
    return links[:20],{'status':'partial' if failures else 'working','queries':completed,'links':len(links),'errors':failures}


def route_links(links,sources):
    routed={};uncovered=[]
    for url in links:
        host=urlparse(url).hostname
        match=next((s for s in sources if s.get('enabled',True) and host in s['hosts']),None)
        if match:routed.setdefault(match['key'],[]).append(url)
        else:
            policy=next((reason for domain,reason in PLATFORM_POLICIES.items() if host==domain or host.endswith('.'+domain)), 'unreviewed domain; not fetched automatically')
            uncovered.append({'url':url,'reason':policy})
    return routed,uncovered
