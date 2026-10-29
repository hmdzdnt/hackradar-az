"""Bounded public HTML, RSS/Atom and sitemap connectors. No restricted-site scraping."""
import re
import html
from urllib.parse import urljoin,urlparse
from xml.etree import ElementTree as ET
from bs4 import BeautifulSoup
from .urls import canonical_url

PRIMARY = re.compile(r'hackathon|hackaton|hakaton|h[əe]katon|хакатон',re.I)
KEYWORDS = re.compile(r'hackathon|hackaton|hakaton|h[əe]katon|хакатон|coding marathon|innovation challenge|proqramlaşdırma yarışı|kodlaşdırma marafonu|инновационн\w* (?:конкурс|соревнован)|марафон программирования',re.I)
SEARCH_QUERIES = [
 'hakaton Azərbaycan qeydiyyat','hackathon Azerbaijan registration','хакатон Азербайджан регистрация',
 'hackaton Baku','Bakı süni intellekt hakaton','AI hackathon Azerbaijan',
 'kibertəhlükəsizlik hakaton Azərbaycan','cybersecurity hackathon Azerbaijan','хакатон Баку кибербезопасность',
 'coding marathon Azerbaijan','innovation challenge Azerbaijan prototype teams','proqramlaşdırma yarışı Azərbaycan',
 'site:devpost.com Azerbaijan hackathon','site:lu.ma Baku hackathon','site:eventbrite.com Azerbaijan hackathon',
 'site:linkedin.com hackathon Azerbaijan','site:instagram.com hakaton Bakı','site:t.me хакатон Баку',
 'site:facebook.com hackathon Azerbaijan','site:x.com hackathon Azerbaijan','site:tiktok.com hackathon Azerbaijan','site:youtube.com hackathon Azerbaijan',
]


def xml_root(content):
    if '<!DOCTYPE' in content.upper() or '<!ENTITY' in content.upper():raise ValueError('Unsafe XML')
    return ET.fromstring(content)


def links_from(content,base,kind,hosts):
    candidates=[]
    if kind=='html':
        soup=BeautifulSoup(content,'html.parser')
        candidates=[(a.get('href',''),a.get_text(' ',strip=True)) for a in soup.select('a[href]')]
    else:
        root=xml_root(content)
        for node in root.iter():
            tag=node.tag.rsplit('}',1)[-1]
            if tag in ('item','entry'):
                title=' '.join(n.text or '' for n in node.iter() if n.tag.rsplit('}',1)[-1]=='title')
                for link in node.iter():
                    if link.tag.rsplit('}',1)[-1]=='link':candidates.append((link.get('href') or link.text or '',title))
            elif tag=='loc':candidates.append((node.text or '', ''))
    urls=[]
    for href,label in candidates:
        url=canonical_url(urljoin(base,href))
        if url and urlparse(url).hostname in hosts and KEYWORDS.search(label+' '+url) and url not in urls:urls.append(url)
    return urls[:24]


def sitemap_children(content,base,hosts):
    root=xml_root(content)
    if root.tag.rsplit('}',1)[-1]!='sitemapindex':return []
    urls=[]
    for node in root.iter():
        if node.tag.rsplit('}',1)[-1]=='loc':
            url=canonical_url(urljoin(base,node.text or ''))
            if url and urlparse(url).hostname in hosts:urls.append(url)
    # A single level and two child documents; never traverse a whole site's history.
    return urls[:2]


def feed_announcements(content,source):
    root=xml_root(content)
    for item in root.iter():
        if item.tag.rsplit('}',1)[-1] not in ('item','entry'):continue
        title=next((n.text or '' for n in item if n.tag.rsplit('}',1)[-1]=='title'),'')
        if not KEYWORDS.search(title):continue
        links=[n.get('href') or n.text or '' for n in item if n.tag.rsplit('}',1)[-1]=='link']
        url=next((canonical_url(u) for u in links if canonical_url(u) and urlparse(u).hostname in source['hosts']),None)
        if not url:continue
        description=' '.join(n.text or '' for n in item.iter() if n.tag.rsplit('}',1)[-1] in ('description','summary','content','encoded'))
        published=next((n.text or '' for n in item if n.tag.rsplit('}',1)[-1] in ('published','pubDate')),'')
        yield url,'<article><h1>'+html.escape(title)+'</h1><time datetime="'+html.escape(published,quote=True)+'"></time>'+description+'</article>'


def telegram_announcements(content,source):
    soup=BeautifulSoup(content,'html.parser')
    for post in soup.select('.tgme_widget_message')[:20]:
        message=post.select_one('.tgme_widget_message_text')
        link=post.select_one('a.tgme_widget_message_date[href]')
        if not message or not link:continue
        text=message.get_text('\n',strip=True)
        title=next((line for line in text.splitlines() if KEYWORDS.search(line)),None)
        url=canonical_url(link['href'])
        if title and url and urlparse(url).hostname in source['hosts']:
            yield url,'<article><h1>'+html.escape(title[:300])+'</h1>'+str(message)+'</article>'


def official_links(content,sources):
    result=[]
    for a in BeautifulSoup(content,'html.parser').select('a[href]'):
        url=canonical_url(a['href'])
        if not url:continue
        label=a.get_text(' ',strip=True)
        if not KEYWORDS.search(label+' '+url) and not re.search(r'official|rəsmi|официаль',label,re.I):continue
        source=next((s for s in sources if s.get('trusted') and s.get('enabled',True) and urlparse(url).hostname in s['hosts']),None)
        if source:result.append((source,url))
    return result[:1]


async def discover(source,fetcher):
    max_pages=min(6,int(source.get('max_pages',6)))
    content,final=await fetcher.get(source['url'])
    seen={canonical_url(final)}
    if source.get('adapter')=='telegram':
        for announcement in telegram_announcements(content,source):yield announcement
        return
    elif source['kind']=='rss':
        for announcement in list(feed_announcements(content,source))[:max_pages-1]:yield announcement
    elif source['kind']=='html':yield final,content
    urls=list(source.get('seeds',[]))+links_from(content,final,source['kind'],source['hosts'])
    feeds=[]
    if source['kind']=='html':
        soup=BeautifulSoup(content,'html.parser')
        for link in soup.select('link[rel="alternate"][href]'):
            if link.get('type') in ('application/rss+xml','application/atom+xml'):feeds.append(urljoin(final,link['href']))
    feeds+=source.get('feeds',[])+source.get('sitemaps',[])
    if source['kind']=='sitemap':feeds+=sitemap_children(content,final,source['hosts'])
    # Optional feeds/sitemaps share the same source page budget.
    for url in list(dict.fromkeys(feeds))[:2]:
        url=canonical_url(url)
        if len(seen)>=max_pages or not url or urlparse(url).hostname not in source['hosts']:continue
        if url in seen:continue
        seen.add(url)
        try:
            text,resolved=await fetcher.get(url)
            urls+=links_from(text,resolved,'rss' if 'feed' in url or 'rss' in url else 'sitemap',source['hosts'])
            for child in sitemap_children(text,resolved,source['hosts']):
                if len(seen)>=max_pages:break
                seen.add(child)
                child_text,child_url=await fetcher.get(child)
                urls+=links_from(child_text,child_url,'sitemap',source['hosts'])
        except Exception as e:yield url,e
    for raw in dict.fromkeys(urls):
        url=canonical_url(raw)
        if len(seen)>=max_pages:break
        if not url or url in seen or urlparse(url).hostname not in source['hosts']:continue
        seen.add(url)
        try:
            text,resolved=await fetcher.get(url)
            yield resolved,text
        except Exception as e:yield url,e
