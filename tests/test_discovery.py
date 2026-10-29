import asyncio
from copy import deepcopy
from datetime import date
import json
import socket
from pathlib import Path
import unittest
from unittest.mock import patch
import httpx
from discovery.connectors import links_from
from discovery.extract import extract, verify, duplicate, explicit_dates, fingerprint
from discovery.network import Fetcher, safe_url
from discovery.store import Store

FIXTURE = Path(__file__).parent / 'fixtures/announcement.html'
SOURCE = {'name':'Fixture university','trusted':True,'context':'Azerbaijan','hosts':['university.example.org']}
URL = 'https://university.example.org/hackathon'

class ExtractionTests(unittest.TestCase):
    def event(self):
        return extract(FIXTURE.read_text(),URL,SOURCE)
    def test_explicit_extraction_and_null_unknowns(self):
        e=self.event()
        self.assertEqual(e['start_date'],'2026-11-21')
        self.assertEqual(e['end_date'],'2026-11-22')
        self.assertEqual(e['city'],'Bakı'); self.assertIsNone(e['age_min']); self.assertIsNone(e['organizer'])
        self.assertEqual(e['registration_status'],'open')
        self.assertEqual(e['registration_deadline'],'2026-11-09T23:59:59+04:00')
        self.assertEqual(verify(e,SOURCE,today=date(2026,10,28)),[])
    def test_no_inferred_open_registration(self):
        e=extract(FIXTURE.read_text().replace('Registration is open.','Learn more.'),URL,SOURCE)
        self.assertEqual(e['registration_status'],'unknown')
    def test_missing_dates_not_published(self):
        e=self.event();e['start_date']=None
        self.assertIn('missing_or_invalid_event_date',verify(e,SOURCE))
        self.assertFalse(e['published'])
    def test_invalid_range_and_untrusted_source(self):
        e=self.event();e['end_date']='2026-01-01'
        self.assertIn('invalid_end_date',verify(e,SOURCE))
        self.assertIn('untrusted_source',verify(self.event(),{**SOURCE,'trusted':False}))
    def test_deadline_is_not_event_date(self):
        self.assertEqual(explicit_dates('Registration deadline: 9 November 2026'),(None,None,None))
        self.assertEqual(explicit_dates('The hackathon will be held on February 30, 2026.'),(None,None,None))
    def test_azerbaijani_dates(self):
        start,end,_=explicit_dates('Yarışma günləri: 1-3 may 2026')
        self.assertEqual((start,end),('2026-05-01','2026-05-03'))
    def test_publication_year_only_with_explicit_reference(self):
        self.assertEqual(explicit_dates('The competition will take place on October 18–19 this year.',2025)[:2],('2025-10-18','2025-10-19'))
        self.assertIsNone(explicit_dates('The competition will take place on October 18–19.',2025)[0])
    def test_duplicate_and_year_separation(self):
        a=self.event();b=deepcopy(a);b['title']='Registration has opened for the “Fixture Hackathon,”';b['official_source_url']='https://university.example.org/other';b['fingerprint']=fingerprint(b)
        self.assertTrue(duplicate(a,b))
        b['start_date']='2027-11-21';b['fingerprint']=fingerprint(b)
        self.assertFalse(duplicate(a,b))
        b['official_source_url']=URL
        self.assertFalse(duplicate(a,b))
    def test_archive_without_fabricating_deadline(self):
        e=self.event();e['registration_deadline']=None
        verify(e,SOURCE,today=date(2027,1,1))
        self.assertTrue(e['archived']);self.assertEqual(e['registration_status'],'closed');self.assertIsNone(e['registration_deadline'])
    def test_jsonld_and_no_xss_url(self):
        data={'@type':'Event','name':'Fixture Hackathon','startDate':'2026-11-21','endDate':'2026-11-22','location':{'address':{'addressLocality':'Bakı'}},'eventAttendanceMode':'https://schema.org/OnlineEventAttendanceMode'}
        html='<h1>Fixture Hackathon</h1><script type="application/ld+json">'+json.dumps(data)+'</script><p>Azerbaijan</p><p>Registration is open <a href="javascript:alert(1)">register</a></p>'
        e=extract(html,URL,SOURCE)
        self.assertEqual(e['format'],'online');self.assertIsNone(e['registration_url']);self.assertEqual(verify(e,SOURCE),[])
    def test_report_and_non_azerbaijan_rejected(self):
        self.assertIsNone(extract('<h1>Students win Hackathon</h1>',URL,SOURCE))
        e=extract('<h1>Paris Hackathon</h1><p>France</p>',URL,{**SOURCE,'context':''})
        verify(e,SOURCE)
        self.assertEqual(e['evidence']['review']['decision'],'rejected')
    def test_source_title_in_header_survives_cleanup(self):
        e=extract(FIXTURE.read_text().replace('<h1>','<header><h1>').replace('</h1>','</h1></header>'),URL,SOURCE)
        self.assertIsNotNone(e)

class ConnectorTests(unittest.TestCase):
    def test_html_rss_atom_sitemap(self):
        html='<a href="/hackathon">Hakaton Bakı</a><a href="https://evil.test/hackathon">Hackathon</a><a href="/news">News</a>'
        self.assertEqual(links_from(html,URL,'html',SOURCE['hosts']),[URL])
        rss='<rss><channel><item><title>Hackathon</title><link>'+URL+'</link></item></channel></rss>'
        atom='<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Hakaton</title><link href="'+URL+'"/></entry></feed>'
        sitemap='<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>'+URL+'</loc></url></urlset>'
        for kind,xml in [('rss',rss),('rss',atom),('sitemap',sitemap)]:self.assertEqual(links_from(xml,URL,kind,SOURCE['hosts']),[URL])
    def test_unsafe_xml_rejected(self):
        with self.assertRaises(ValueError):links_from('<!DOCTYPE foo><rss/>',URL,'rss',SOURCE['hosts'])
    def test_ssrf_private_and_off_allowlist(self):
        for url in ['http://university.example.org','https://127.0.0.1','https://evil.test','https://user@university.example.org']:
            with self.assertRaises(ValueError):safe_url(url,SOURCE['hosts'])
        with patch('socket.getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',443))]):
            with self.assertRaises(ValueError):safe_url(URL,SOURCE['hosts'])

class NetworkTests(unittest.IsolatedAsyncioTestCase):
    async def test_transient_dns_retried_without_bypassing_validation(self):
        f=Fetcher(SOURCE['hosts'])
        with patch('discovery.network.safe_url',side_effect=[socket.gaierror('temporary'),URL]) as check, patch('discovery.network.asyncio.sleep',return_value=None):
            self.assertEqual(await f.validate(URL),URL)
            self.assertEqual(check.call_count,2)
        await f.close()

    async def test_robots_access_restriction(self):
        calls=[]
        def handler(r):
            calls.append(str(r.url));return httpx.Response(200,text='User-agent: *\nDisallow: /hackathon')
        f=Fetcher(SOURCE['hosts']);await f.client.aclose();f.client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
        with patch('discovery.network.safe_url',side_effect=lambda u,h:u), patch('discovery.network.asyncio.sleep',return_value=None):
            with self.assertRaises(PermissionError):await f.get(URL)
        self.assertEqual(len(calls),1);await f.close()
    async def test_restricted_fetch_not_retried(self):
        calls=[]
        def handler(r):
            calls.append(str(r.url));return httpx.Response(404 if r.url.path=='/robots.txt' else 403)
        f=Fetcher(SOURCE['hosts']);await f.client.aclose();f.client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
        with patch('discovery.network.safe_url',side_effect=lambda u,h:u), patch('discovery.network.asyncio.sleep',return_value=None):
            with self.assertRaises(PermissionError):await f.get(URL)
        self.assertEqual(len(calls),2);await f.close()

class DatabaseClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_idempotent_existing_source_updates_and_parameterized_queries(self):
        calls=[]
        def handler(r):
            calls.append(r)
            if r.url.path.endswith('/event_sources') and r.method=='GET':return httpx.Response(200,json=[{'event_id':'event-1'}])
            if r.url.path.endswith('/hackathons') and r.method=='GET':return httpx.Response(200,json=[{'id':'event-1','title':'“Fixture Hackathon”','start_date':'2026-11-21','official_source_url':URL}])
            if r.method=='PATCH':return httpx.Response(200,json=[{'id':'event-1'}])
            return httpx.Response(200,json=[])
        with patch.dict('os.environ',{'SUPABASE_URL':'https://example.supabase.co','SUPABASE_SERVICE_ROLE_KEY':'test-only'}):store=Store()
        await store.client.aclose();store.client=httpx.AsyncClient(base_url='https://example.supabase.co/rest/v1/',transport=httpx.MockTransport(handler))
        e=extract(FIXTURE.read_text(),URL,SOURCE);verify(e,SOURCE)
        result=await store.save(e,'source-1','abc')
        self.assertEqual(result['id'],'event-1')
        self.assertEqual(calls[2].method,'PATCH');self.assertEqual(calls[2].url.params['id'],'eq.event-1')
        await store.close()

if __name__=='__main__':unittest.main()
