"""Synthetic fixtures only; no network or production inserts."""
import asyncio
from copy import deepcopy
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
import httpx
from discovery.dates import explicit_dates,lifecycle,timestamp
from discovery.extract import extract,extract_candidates,verify,duplicate,fingerprint
from discovery.relevance import location_evidence
from discovery.urls import canonical_url
from discovery.connectors import feed_announcements,telegram_announcements,sitemap_children,official_links,links_from,SEARCH_QUERIES
from discovery.network import RequestBudget,BudgetExceeded
from discovery.search import search_links,queries_for_slot,route_links
from discovery.store import Store,DatabaseError
from discovery.run import run,select_sources

NOW=datetime(2026,10,28,12,tzinfo=timezone.utc)
SOURCE={'key':'fixture','name':'Fixture','url':'https://official.example.org/news','kind':'html','trusted':True,'hosts':['official.example.org']}
URL='https://official.example.org/hackathon'

def page(**changes):
    data={'@type':'Event','name':'Fixture Hackathon','startDate':'2026-11-21T10:00:00+04:00','endDate':'2026-11-22T18:00:00+04:00','location':{'name':'Fixture venue','address':{'addressLocality':'Baku','addressCountry':'AZ'}},'organizer':{'name':'Fixture Organizer'}}
    data.update(changes)
    return '<main><h1>'+data['name']+'</h1><script type="application/ld+json">'+json.dumps(data)+'</script></main>'

def event(**changes):return extract(page(**changes),URL,SOURCE)

class QualityTests(unittest.TestCase):
    def test_incidental_country_mention_is_not_eligibility(self):
        html=page(location={'address':{'addressLocality':'Paris','addressCountry':'FR'}})+'<p>Organizer has an office in Azerbaijan. Teams from Baku won last year.</p>'
        e=extract(html,URL,SOURCE);verify(e,SOURCE,now=NOW)
        self.assertEqual(e['evidence']['review']['decision'],'rejected')
        self.assertFalse(e['published'])
    def test_explicit_online_eligibility_and_physical_venue(self):
        evidence,_,_=location_evidence({},'Open to participants based in Azerbaijan.',SOURCE)
        self.assertEqual(evidence['kind'],'explicit_participant_eligibility')
        evidence,city,_=location_evidence({},'Venue: Bakı, Azerbaijan',SOURCE)
        self.assertEqual(city,'Bakı');self.assertEqual(evidence['kind'],'physical_location')
    def test_global_availability_and_foreign_venue_do_not_target_azerbaijan(self):
        for text in ['Open to anyone worldwide, including Azerbaijan.',
                     'The hackathon will be held in Paris with guests from Baku.',
                     'Venue: Paris, France; partners from Azerbaijan']:
            self.assertIsNone(location_evidence({},text,SOURCE)[0],text)
        self.assertIsNotNone(location_evidence({},'The hackathon will take place in Baku.',SOURCE)[0])
        self.assertIsNotNone(location_evidence({},'For Azerbaijan-based participants.',SOURCE)[0])
    def test_official_local_venue_requires_hosting_statement(self):
        s={**SOURCE,'local_venues':{'BEU':'Xırdalan'}}
        self.assertIsNotNone(location_evidence({},'The hackathon will be held at BEU.',s)[0])
        self.assertIsNone(location_evidence({},'BEU students travelled to a hackathon in Paris.',s)[0])
    def test_expired_candidates_are_not_publishable(self):
        e=event(startDate='2025-10-18',endDate='2025-10-19');verify(e,SOURCE,now=NOW)
        self.assertEqual(e['evidence']['review']['decision'],'expired');self.assertFalse(e['published'])
    def test_closed_registration_does_not_reject_upcoming_event(self):
        e=event();e['registration_status']='closed';e['registration_deadline']='2026-10-01T23:59:59+04:00'
        self.assertEqual(verify(e,SOURCE,now=NOW),[]);self.assertTrue(e['published']);self.assertEqual(e['registration_status'],'closed')
    def test_missing_and_ambiguous_dates_quarantined(self):
        e=event(startDate=None,endDate=None);verify(e,SOURCE,now=NOW)
        self.assertEqual(e['evidence']['review']['decision'],'quarantined')
        self.assertEqual(explicit_dates('Event dates: 21-22 November 2026\nEvent dates: 23-24 November 2026'),(None,None,None))
    def test_only_explicit_times_and_timezone_conversion(self):
        self.assertIsNone(timestamp('2026-11-21'))
        self.assertEqual(timestamp('2026-11-21T10:00:00'),'2026-11-21T10:00:00+04:00')
        e=event(startDate='2026-11-21T22:00:00Z',endDate='2026-11-22T02:00:00Z')
        self.assertEqual(e['start_date'],'2026-11-22')
    def test_exact_end_and_baku_midnight(self):
        e=event(startDate='2026-10-28T10:00:00+04:00',endDate='2026-10-28T16:00:00+04:00')
        self.assertEqual(lifecycle(e,NOW),'archived')
        date_only=event(startDate='2026-10-28',endDate='2026-10-28')
        self.assertEqual(lifecycle(date_only,datetime.fromisoformat('2026-10-28T23:59:59+04:00')),'ongoing')
        self.assertEqual(lifecycle(date_only,datetime.fromisoformat('2026-10-29T00:00:00+04:00')),'archived')
    def test_russian_iso_cross_year_and_deadline_dates(self):
        self.assertEqual(explicit_dates('Хакатон пройдёт 21–22 ноября 2026 года.')[:2],('2026-11-21','2026-11-22'))
        self.assertEqual(explicit_dates('Event dates: 2026-12-31 to 2027-01-01')[:2],('2026-12-31','2027-01-01'))
        self.assertEqual(explicit_dates('Registration deadline: 9 November 2026. Published 2 January 2026.'),(None,None,None))
    def test_multiple_structured_events_kept_separate(self):
        first=json.loads(page().split('application/ld+json">')[1].split('</script>')[0]);second={**first,'name':'Second Hackathon','url':'https://official.example.org/second'}
        html='<script type="application/ld+json">'+json.dumps([first,second])+'</script><h1>Events</h1>'
        self.assertEqual(len(list(extract_candidates(html,URL,SOURCE))),2)
    def test_url_organizer_editions_and_changed_dates(self):
        self.assertEqual(canonical_url(URL+'/?utm_source=x&b=2#fragment'),URL+'?b=2')
        a=event();b=deepcopy(a);b['start_date']='2027-11-21';b['fingerprint']=fingerprint(b)
        self.assertFalse(duplicate(a,b))
        b=deepcopy(a);b['start_date']='2026-11-28';self.assertTrue(duplicate(a,b))
        b=deepcopy(a);b['start_date']='2026-01-01';b['fingerprint']=fingerprint(b);self.assertFalse(duplicate(a,b))
        b=deepcopy(a);b['official_source_url']='https://official.example.org/other';b['organizer']='Different organizer';b['fingerprint']=fingerprint(b)
        self.assertFalse(duplicate(a,b))
    def test_innovation_challenge_is_not_automatically_a_hackathon(self):
        e=event(name='Fixture innovation challenge');verify(e,SOURCE,now=NOW)
        self.assertIn('unconfirmed_hackathon_format',e['evidence']['review']['reasons'])
    def test_untrusted_social_candidate_stays_private(self):
        e=event();verify(e,{**SOURCE,'trusted':False},now=NOW)
        self.assertEqual(e['evidence']['review']['decision'],'quarantined');self.assertFalse(e['published'])
    def test_request_and_rotation_limits(self):
        budget=RequestBudget(2);budget.consume();budget.consume()
        with self.assertRaises(BudgetExceeded):budget.consume()
        sources=[{**SOURCE,'key':str(i)} for i in range(12)]
        self.assertEqual(len(select_sources(sources,0)),8)
        self.assertEqual(len(set(s['key'] for s in select_sources(sources,0)+select_sources(sources,1))),12)
    def test_inline_public_feed_and_telegram_adapters(self):
        rss='<rss><channel><item><title>Fixture Hackathon</title><link>'+URL+'</link><description>Venue: Baku. Event dates: 21-22 November 2026.</description></item></channel></rss>'
        self.assertEqual(next(feed_announcements(rss,SOURCE))[0],URL)
        source={**SOURCE,'hosts':['t.me']}
        post='<div class="tgme_widget_message"><div class="tgme_widget_message_text">Fixture Hackathon<br>Venue: Baku</div><a class="tgme_widget_message_date" href="https://t.me/fixture/1">date</a></div>'
        self.assertEqual(next(telegram_announcements(post,source))[0],'https://t.me/fixture/1')
    def test_sitemap_depth_and_official_crosscheck_hosts(self):
        xml='<sitemapindex>'+''.join('<sitemap><loc>https://official.example.org/map'+str(i)+'.xml</loc></sitemap>' for i in range(5))+'</sitemapindex>'
        self.assertEqual(len(sitemap_children(xml,URL,SOURCE['hosts'])),2)
        self.assertEqual(len(official_links('<a href="'+URL+'">Official event</a>',[SOURCE])),1)
        self.assertEqual(official_links('<a href="https://evil.test/hackathon">Official event</a>',[SOURCE]),[])

class StorageTests(unittest.IsolatedAsyncioTestCase):
    async def store(self,handler):
        with patch.dict(os.environ,{'SUPABASE_URL':'https://fixture.supabase.co','SUPABASE_SERVICE_ROLE_KEY':'test-only'}):s=Store()
        await s.client.aclose();s.client=httpx.AsyncClient(base_url='https://fixture.supabase.co/rest/v1/',transport=httpx.MockTransport(handler));return s
    async def test_expired_new_never_posted_even_if_marked_published(self):
        calls=[]
        def handler(r):calls.append(r.method);return httpx.Response(200,json=[])
        s=await self.store(handler);e=event(startDate='2020-01-01',endDate='2020-01-02');e['published']=True
        result=await s.save(e,'source','hash');self.assertEqual(result['status'],'expired');self.assertNotIn('POST',calls);await s.close()
    async def test_past_start_unknown_end_is_quarantined_without_insert(self):
        calls=[]
        def handler(r):calls.append(r.method);return httpx.Response(200,json=[])
        s=await self.store(handler);e=event(startDate='2020-01-01',endDate=None);verify(e,SOURCE,now=NOW)
        result=await s.save(e,'source','hash')
        self.assertEqual(result['status'],'quarantined');self.assertNotIn('POST',calls);await s.close()
    async def test_existing_history_archived_without_deletion_or_unpublishing(self):
        calls=[];old={**event(startDate='2020-01-01',endDate='2020-01-02'),'id':'stored','published':True}
        def handler(r):
            calls.append(r)
            if r.url.path.endswith('event_sources') and r.method=='GET':return httpx.Response(200,json=[{'event_id':'stored'}])
            if r.url.path.endswith('hackathons') and r.method=='GET':return httpx.Response(200,json=[old])
            return httpx.Response(200,json=[{'id':'stored'}])
        s=await self.store(handler);result=await s.save(old,'source','hash')
        self.assertEqual(result['id'],'stored');self.assertFalse(any(r.method=='DELETE' for r in calls))
        payload=json.loads(next(r for r in calls if r.method=='PATCH').content);self.assertNotIn('published',payload);self.assertTrue(payload['archived']);await s.close()
    async def test_v1_schema_fallback_and_safe_errors(self):
        s=await self.store(lambda r:httpx.Response(400,json={'code':'42703','message':'private test value'}))
        self.assertFalse(await s.detect_schema());await s.close()
        s=await self.store(lambda r:httpx.Response(401,json={'message':'private test value'}))
        with self.assertRaises(DatabaseError) as caught:await s.detect_schema()
        self.assertNotIn('private test value',str(caught.exception));self.assertEqual(caught.exception.status,401);await s.close()

class SearchTests(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_search_never_networks(self):
        with patch.dict(os.environ,{'DISCOVERY_SEARCH_ENABLED':'false'}):
            links,report=await search_links(0)
        self.assertEqual(links,[]);self.assertEqual(report['status'],'disabled')
    async def test_official_api_bounded_and_quota_is_not_retried(self):
        calls=[]
        def handler(r):calls.append(r);return httpx.Response(429)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with patch.dict(os.environ,{'DISCOVERY_SEARCH_ENABLED':'true','DISCOVERY_SEARCH_API_KEY':'test-only'}):links,report=await search_links(0,client)
        self.assertEqual(len(calls),1);self.assertEqual(report['status'],'partial');self.assertEqual(links,[])
    async def test_search_routing_and_multilingual_rotation(self):
        routed,uncovered=route_links([URL,'https://instagram.com/fixture','https://unknown.test/event'],[SOURCE])
        self.assertEqual(routed['fixture'],[URL]);self.assertEqual(len(uncovered),2)
        self.assertTrue(any('хакатон' in q for q in SEARCH_QUERIES));self.assertEqual(len(queries_for_slot(0)),4)

class RunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_source_does_not_stop_later_source(self):
        class FakeFetcher:
            def __init__(self,*args):pass
            async def close(self):pass
        async def connector(source,fetcher):
            if source['key']=='bad':raise PermissionError('robots.txt disallows URL')
            yield URL,page()
        with patch('discovery.run.Fetcher',FakeFetcher),patch('discovery.run.discover',connector),patch.dict(os.environ,{'DISCOVERY_SEARCH_ENABLED':'false'}):
            result=await run(True,sources=[{**SOURCE,'key':'bad'},SOURCE])
        self.assertEqual(result['status'],'partial');self.assertEqual(result['counts']['accepted'],1);self.assertEqual(result['counts']['source_errors'],1)
    async def test_untrusted_announcement_can_be_corroborated_officially(self):
        social={**SOURCE,'key':'social','trusted':False,'url':'https://social.example.org/channel','hosts':['social.example.org']}
        social_url='https://social.example.org/post'
        class FakeFetcher:
            def __init__(self,*args):pass
            async def close(self):pass
            async def get(self,url):return page(),URL
        async def connector(source,fetcher):
            if source['key']=='social':yield social_url,page()+'<a href="'+URL+'">Official event</a>'
            else:yield SOURCE['url'],'<h1>News</h1>'
        with patch('discovery.run.Fetcher',FakeFetcher),patch('discovery.run.discover',connector),patch.dict(os.environ,{'DISCOVERY_SEARCH_ENABLED':'false'}):
            result=await run(True,sources=[social,SOURCE])
        self.assertEqual(result['counts']['accepted'],1)
        self.assertEqual(result['events'][0]['announcement_url'],social_url)
        self.assertEqual(result['events'][0]['official_source_url'],URL)

    async def test_write_failure_not_counted_as_accepted_or_success(self):
        class FakeFetcher:
            def __init__(self,*args):pass
            async def close(self):pass
        class BrokenStore:
            extended_schema=False
            async def request(self,*args,**kwargs):return [{'id':'run'}]
            async def detect_schema(self):return False
            async def source(self,*args):return 'source'
            async def save(self,*args,**kwargs):raise DatabaseError('POST','hackathons',400,'23514')
            async def close(self):pass
        async def connector(*args):yield URL,page()
        with patch('discovery.run.Fetcher',FakeFetcher),patch('discovery.run.discover',connector),patch('discovery.run.Store',BrokenStore),patch.dict(os.environ,{'DISCOVERY_SEARCH_ENABLED':'false'}):
            result=await run(False,sources=[SOURCE])
        self.assertEqual(result['status'],'failed');self.assertEqual(result['counts']['accepted'],0);self.assertEqual(result['counts']['write_errors'],1)

if __name__=='__main__':unittest.main()
