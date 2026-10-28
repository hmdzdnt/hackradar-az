import re
from urllib.parse import urljoin, urlparse, urldefrag
from xml.etree import ElementTree as ET
from bs4 import BeautifulSoup

KEYWORDS = re.compile(r'hackathon|hakaton|h[əe]katon|proqramlaşdırma yarışı', re.I)
SEARCH_QUERIES = ['hakaton Azərbaycan', 'hackathon Azerbaijan', 'hackathon Baku', 'Bakı hakaton', 'AI hackathon Azerbaijan', 'kibertəhlükəsizlik hakaton', 'proqramlaşdırma yarışı']


def links_from(content, base, kind, hosts):
    """Connectors accept public HTML, RSS/Atom and XML sitemaps; no search scraping."""
    candidates = []
    if kind == 'html':
        soup = BeautifulSoup(content, 'html.parser')
        candidates = [(a.get('href', ''), a.get_text(' ', strip=True)) for a in soup.select('a[href]')]
    else:
        # Reject DTDs/entities even though stdlib does not resolve external entities.
        if '<!DOCTYPE' in content.upper() or '<!ENTITY' in content.upper():
            raise ValueError('Unsafe XML')
        root = ET.fromstring(content)
        for node in root.iter():
            tag = node.tag.rsplit('}', 1)[-1]
            if tag in ('item', 'entry'):
                title = ' '.join(n.text or '' for n in node.iter() if n.tag.rsplit('}', 1)[-1] == 'title')
                for link in node.iter():
                    if link.tag.rsplit('}', 1)[-1] == 'link':
                        candidates.append((link.get('href') or link.text or '', title))
            elif tag == 'loc':
                candidates.append((node.text or '', ''))
    urls = []
    for href, label in candidates:
        url = urldefrag(urljoin(base, href))[0]
        p = urlparse(url)
        if p.scheme == 'https' and p.hostname in hosts and KEYWORDS.search(label + ' ' + url) and url not in urls:
            urls.append(url)
    return urls[:24]


async def discover(source, fetcher):
    content, final = await fetcher.get(source['url'])
    urls = links_from(content, final, source['kind'], source['hosts'])
    if source['kind'] == 'html' and KEYWORDS.search(BeautifulSoup(content, 'html.parser').get_text(' ', strip=True)):
        yield final, content
    for url in dict.fromkeys(source.get('seeds', []) + urls):
        if url != final:
            try:
                text, resolved = await fetcher.get(url)
                yield resolved, text
            except Exception as e:
                # Report partial source failures to the runner; never silently swallow them.
                yield url, e
