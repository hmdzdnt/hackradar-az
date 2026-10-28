"""Conservative evidence extraction. Missing or ambiguous facts stay null."""
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
import hashlib
import json
import re
import unicodedata
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from .connectors import KEYWORDS

MONTHS = {'january':1,'february':2,'march':3,'april':4,'may':5,'june':6,'july':7,'august':8,'september':9,'october':10,'november':11,'december':12,'yanvar':1,'fevral':2,'mart':3,'aprel':4,'may':5,'iyun':6,'iyul':7,'avqust':8,'sentyabr':9,'oktyabr':10,'noyabr':11,'dekabr':12}
MONTH = '|'.join(MONTHS)
AZ = re.compile(r'azerbaijan|azərbaycan|baku|bakı|sumqay[ıi]t|g[əa]nc[əa]|x[ıi]rdalan|qarabağ|karabakh', re.I)
TOPICS = {'Süni intellekt':r'artificial intelligence|süni intellekt|\bAI\b', 'Kibertəhlükəsizlik':r'cybersecurity|kibertəhlükəsizlik|cybercell', 'Enerji':r'energy|enerji|quyu|well performance', 'Ağıllı şəhər':r'smart cit|ağıllı şəhər|urban', 'Proqramlaşdırma':r'programming|proqramlaşdırma'}


def iso_day(value):
    if not value or not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value[:10]).isoformat()
    except ValueError:
        return None


def safe_link(value):
    if not isinstance(value, str):
        return None
    try:
        p = urlparse(value)
        return value if p.scheme == 'https' and p.hostname and not p.username and not p.password and p.port in (None,443) else None
    except ValueError:
        return None


def normalize(value):
    return re.sub(r'[^\w]+', ' ', unicodedata.normalize('NFKC', value).casefold()).strip()


def canonical_title(title):
    for quote in re.findall(r'[“\"«]([^”\"»]+)[”\"»]',title):
        if KEYWORDS.search(quote):
            return normalize(quote)
    return normalize(title)


def fingerprint(event):
    # Year separates editions. Source-URL identity is also checked before title matching.
    title = canonical_title(event['title'])
    title = re.sub(r'^(registration has opened for the|qeydiyyat başladı|the)\s+', '', title)
    year = (event.get('start_date') or '')[:4]
    return hashlib.sha256(f'{title}|{year}'.encode()).hexdigest()


def duplicate(a, b):
    if a.get('official_source_url') == b.get('official_source_url'):
        return True
    if a.get('fingerprint') and a['fingerprint'] == b.get('fingerprint'):
        return True
    # Exact normalized event identity/date, independent of organizer spelling.
    def identity(e):
        t = canonical_title(e['title'])
        m = re.search(r'([\w]+(?: [\w]+){0,3} hackathon)(?: (20\d{2}))?', t)
        return m.group(0) if m else t
    return bool(a.get('start_date') and a.get('start_date') == b.get('start_date') and identity(a) == identity(b))


def json_events(soup):
    def walk(node):
        if isinstance(node, list):
            for v in node:
                yield from walk(v)
        elif isinstance(node, dict):
            types = node.get('@type', [])
            if 'Event' in (types if isinstance(types, list) else [types]):
                yield node
            if '@graph' in node:
                yield from walk(node['@graph'])
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            yield from walk(json.loads(script.string or script.get_text()))
        except (ValueError, TypeError):
            continue


def explicit_dates(text, publication_year=None):
    """Only event-date sentences, never article timestamps or registration deadlines."""
    for sentence in re.split(r'(?<=[.!?])\s+|\n', text):
        if not re.search(r'will (?:take place|be held)|yarışma günləri|tədbir.*keçiriləcək|hakaton.*keçiriləcək|event dates|tarixlərində', sentence, re.I):
            continue
        # An explicit year in the sentence, or 'this year' tied to an explicit article year.
        years = re.findall(r'\b(20\d{2})\b', sentence)
        year = int(years[-1]) if len(set(years)) == 1 else publication_year if re.search(r'this year|bu il', sentence, re.I) else None
        if not year:
            continue
        en = re.search(rf'\b({MONTH})\s+(\d{{1,2}})\b(?:\s*[–−-]\s*(\d{{1,2}})\b)?', sentence, re.I)
        az = re.search(rf'\b(\d{{1,2}})(?:\s*[–−-]\s*(\d{{1,2}}))?\s+({MONTH})\b', sentence, re.I)
        try:
            if en:
                m, first, last = MONTHS[en[1].lower()], int(en[2]), int(en[3]) if en[3] else None
            elif az:
                m, first, last = MONTHS[az[3].lower()], int(az[1]), int(az[2]) if az[2] else None
            else:
                continue
            return date(year,m,first).isoformat(), date(year,m,last).isoformat() if last else None, sentence.strip()
        except ValueError:
            continue
    return None, None, None


def extract(html, url, source):
    soup = BeautifulSoup(html, 'html.parser')
    structured = list(json_events(soup))
    original_heading = soup.find('h1')
    heading_text = original_heading.get_text(' ',strip=True) if original_heading else None
    for node in soup.select('script,style,nav,footer,header,aside'):
        node.decompose()
    article = (soup.body if urlparse(url).hostname == 'hackathon.socar.az' else None) or soup.select_one('article') or soup.select_one('main') or soup.body or soup
    title_node = article.find('h1') or soup.find('h1')
    title = title_node.get_text(' ', strip=True) if title_node else heading_text
    text = article.get_text('\n', strip=True)
    data = next((n for n in structured if KEYWORDS.search(str(n.get('name','')))), None)
    if data:
        title = data.get('name')
    if not isinstance(title, str) or not KEYWORDS.search(title) or len(title) > 300:
        return None
    # Listings and reports of winners do not establish a new announcement.
    if re.search(r'\bwin(?:s|ners)?\b|qalib|nəticələr|infosession|info session', title, re.I):
        return None
    if not AZ.search(text):
        return None
    fields = ['organizer','description','city','format','start_date','end_date','registration_deadline','registration_url','age_min','age_max','age_restrictions','team_requirements','prize_info','has_prize','topics']
    event = dict.fromkeys(fields)
    event.update(title=title.strip(), official_source_url=url, registration_status='unknown', registration_evidence=None, evidence={})
    paragraphs = [p.get_text(' ', strip=True) for p in article.select('p') if len(p.get_text(' ', strip=True)) > 30]
    # Store a short source excerpt; full facts remain in the evidence payload.
    description = next((p for p in paragraphs if KEYWORDS.search(p)), None)
    event['description'] = description[:700] if description else None
    if data:
        event['start_date'] = iso_day(data.get('startDate'))
        event['end_date'] = iso_day(data.get('endDate'))
        organizer = data.get('organizer')
        if isinstance(organizer, dict):
            event['organizer'] = organizer.get('name')
        location = data.get('location')
        if isinstance(location, dict) and isinstance(location.get('address'), dict):
            event['city'] = location['address'].get('addressLocality')
        mode = data.get('eventAttendanceMode', '')
        event['format'] = {'https://schema.org/OfflineEventAttendanceMode':'onsite','https://schema.org/OnlineEventAttendanceMode':'online','https://schema.org/MixedEventAttendanceMode':'hybrid'}.get(mode)
        event['evidence']['jsonld'] = data
    if not event['start_date']:
        # Find an explicit publication year only from metadata or <time>.
        original = BeautifulSoup(html, 'html.parser')
        pub = original.select_one('meta[property="article:published_time"],time[datetime]')
        year_text = pub.get('content', pub.get('datetime','')) if pub else ''
        match = re.match(r'(20\d{2})', year_text)
        if not match:
            # BEU renders a standalone publication date as a paragraph.
            pub_text = next((p.get_text(' ',strip=True) for p in original.select('p') if re.fullmatch(rf'(?:{MONTH}) \d{{1,2}}, 20\d{{2}}',p.get_text(' ',strip=True),re.I)), '')
            match = re.search(r'(20\d{2})',pub_text)
        start, end, quote = explicit_dates(text, int(match[1]) if match else None)
        event.update(start_date=start, end_date=end)
        if quote:
            event['evidence']['dates'] = quote
    lines = list(dict.fromkeys([p.get_text(' ',strip=True) for p in article.select('p,li,tr')] + [re.sub(r'\s+', ' ', line).strip() for line in text.splitlines() if line.strip()]))
    def line_matching(pattern):
        return next((line[:700] for line in lines if re.search(pattern,line,re.I)), None)
    event['age_restrictions'] = line_matching(r'\b\d{1,2}\s*(?:yaş|years old)|age (?:limit|restriction)|students.*(?:participate|join)|şagird.*iştirak|tələb.*iştirak')
    event['team_requirements'] = line_matching(r'team.*(?:maximum|up to|members|consist)|komanda.*(?:nəfər|üzv)')
    event['prize_info'] = line_matching(r'(?:prize|mükafat|place|yer).{0,100}\d[\d ,]*(?:AZN|manat)|(?:AZN|manat).{0,50}(?:prize|mükafat)')
    event['has_prize'] = True if event['prize_info'] else None
    event['topics'] = [k for k, pattern in TOPICS.items() if re.search(pattern,text,re.I)] or None
    # Registration links need explicit registration context, not arbitrary outbound links.
    for a in article.select('a[href]'):
        surrounding = a.parent.get_text(' ', strip=True)
        preceding = a.parent.find_previous_sibling()
        context = surrounding + ' ' + (preceding.get_text(' ',strip=True) if preceding else '')
        if re.search(r'register|registration|qeydiyyat|müraciət',context,re.I):
            link = safe_link(a.get('href'))
            if link:
                event['registration_url'] = link
                break
    open_quote = line_matching(r'registration (?:has opened|is open)|must register|qeydiyyat başladı|qeydiyyat açıq|qeydiyyatdan keç')
    closed_quote = line_matching(r'registration (?:is closed|has closed)|qeydiyyat başa çat|qeydiyyat bağlan')
    if closed_quote:
        event.update(registration_status='closed', registration_evidence=closed_quote)
    elif open_quote and event['registration_url']:
        event.update(registration_status='open', registration_evidence=open_quote)
    deadline = line_matching(r'(?:son (?:müraciət|qeydiyyat) tarixi|müraciət üçün son tarix|registration deadline|apply by)')
    if deadline:
        m = re.search(rf'(\d{{1,2}})\s+({MONTH})\s+(20\d{{2}})',deadline,re.I)
        if m:
            try:
                event['registration_deadline'] = f'{date(int(m[3]),MONTHS[m[2].lower()],int(m[1])).isoformat()}T23:59:59+04:00'
                event['evidence']['deadline'] = deadline
            except ValueError:
                pass
    _official_adapter(event, article, url)
    event['evidence']['source_title'] = title
    if not event['organizer']:
        organizer_quote = next((re.search(r'^(.+?) are jointly organizing',p) for p in paragraphs if re.search(r'^(.+?) are jointly organizing',p)),None)
        if organizer_quote:
            event['organizer'] = organizer_quote[1]
            event['evidence']['organizer'] = organizer_quote[0]
    event['evidence']['azerbaijan'] = AZ.search(text)[0]
    event['fingerprint'] = fingerprint(event)
    return event


def verify(event, source, today=None):
    today = today or datetime.now(ZoneInfo('Asia/Baku')).date()
    problems = []
    start = iso_day(event.get('start_date'))
    end = iso_day(event.get('end_date'))
    if not source.get('trusted'):
        problems.append('untrusted_source')
    if not KEYWORDS.search(event.get('title','')):
        problems.append('not_hackathon')
    if not start:
        problems.append('missing_or_invalid_event_date')
    elif not date(2010,1,1) <= date.fromisoformat(start) <= date(today.year+3,12,31):
        problems.append('implausible_event_date')
    if event.get('end_date') and (not end or (start and end < start)):
        problems.append('invalid_end_date')
    if urlparse(event.get('official_source_url','')).hostname not in source['hosts']:
        problems.append('source_host_mismatch')
    if not event.get('evidence',{}).get('azerbaijan'):
        problems.append('no_azerbaijan_evidence')
    if not (event.get('evidence',{}).get('dates') or event.get('evidence',{}).get('jsonld')):
        problems.append('no_date_evidence')
    now = datetime.now(timezone.utc)
    expired = bool(start and date.fromisoformat(end or start) < today)
    if expired or (event.get('registration_deadline') and datetime.fromisoformat(event['registration_deadline']) < now):
        event['registration_status'] = 'closed'
    event.update(verified=not problems,published=not problems,archived=expired,last_verified_at=now.isoformat() if not problems else None)
    return problems


def _official_adapter(event, article, url):
    """An audited adapter for the working official SOCAR event landing page."""
    if urlparse(url).hostname != 'hackathon.socar.az':
        return
    flat = article.get_text(' ',strip=True)
    for row in article.select('tr'):
        cells = row.find_all(['td','th'])
        if len(cells) == 2 and KEYWORDS.search(cells[1].get_text()):
            m = re.fullmatch(r'(\d{1,2})[–-](\d{1,2}) (November|noyabr) (20\d{2})',cells[0].get_text(' ',strip=True),re.I)
            if m:
                try:
                    event['start_date'] = date(int(m[4]),11,int(m[1])).isoformat()
                    event['end_date'] = date(int(m[4]),11,int(m[2])).isoformat()
                    event['evidence']['dates'] = row.get_text(' ',strip=True)
                except ValueError:
                    pass
    organizer = re.search(r'hackathon organised by (.+?) \.',flat)
    if organizer:
        event['organizer'] = organizer[1]
        event['evidence']['organizer'] = organizer[0]
    if 'Sabah City, Baku' in flat:
        event['city'] = 'Bakı'
        event['evidence']['city'] = 'Sabah City, Baku'
    if 'In-person attendance is required' in flat:
        event['format'] = 'onsite'
        event['evidence']['format'] = 'In-person attendance is required'
    age = re.search(r'Participants must be (\d{1,2}) years of age or older',flat)
    if age:
        event['age_min'] = int(age[1])
        event['age_restrictions'] = age[0]
    team = re.search(r'Teams may have up to (?:three|3) members',flat)
    if team:
        event['team_requirements'] = team[0]
    prizes = re.search(r'Prizes (.+?) Who can apply',flat)
    if prizes:
        event['prize_info'] = prizes[1]
        event['has_prize'] = True
    deadline = re.search(r'Registration closes on (\d{1,2}) (November|noyabr) (20\d{2}) \(23:59\)',flat,re.I)
    if deadline:
        event['registration_deadline'] = f'{date(int(deadline[3]),11,int(deadline[1])).isoformat()}T23:59:59+04:00'
        event['evidence']['deadline'] = deadline[0]
    if 'Registration is open to individuals and teams' in flat and event['registration_url']:
        event['registration_status'] = 'open'
        event['registration_evidence'] = 'Registration is open to individuals and teams'
