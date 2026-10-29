"""Explicit event dates only. Date-only end boundaries are exclusive next midnight."""
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
import re

BAKU = ZoneInfo('Asia/Baku')
MONTHS = {
 'january':1,'february':2,'march':3,'april':4,'may':5,'june':6,'july':7,'august':8,'september':9,'october':10,'november':11,'december':12,
 'yanvar':1,'fevral':2,'mart':3,'aprel':4,'iyun':6,'iyul':7,'avqust':8,'sentyabr':9,'oktyabr':10,'noyabr':11,'dekabr':12,
 'января':1,'февраля':2,'марта':3,'апреля':4,'мая':5,'июня':6,'июля':7,'августа':8,'сентября':9,'октября':10,'ноября':11,'декабря':12,
}
MONTH = '|'.join(sorted(MONTHS,key=len,reverse=True))
EVENT_DATE = re.compile(r'will (?:take place|be held)|yarışma günləri|(?:tədbir|hakaton).*keçiriləcək|event dates|tarixlərində|даты? (?:проведения|хакатона)|(?:хакатон|соревнование).*?(?:пройд[её]т|состоится)',re.I)
DEADLINE = re.compile(r'deadline|apply by|registration closes|son (?:müraciət|qeydiyyat)|müraciət üçün son|son tarix|срок.*(?:регистрац|заяв)|при[её]м заявок',re.I)


def iso_day(value):
    if not isinstance(value,str): return None
    try: return date.fromisoformat(value[:10]).isoformat()
    except ValueError: return None


def timestamp(value, zone='Asia/Baku'):
    if not isinstance(value,str) or not re.match(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}',value): return None
    try:
        result=datetime.fromisoformat(value.replace('Z','+00:00'))
        return (result if result.tzinfo else result.replace(tzinfo=ZoneInfo(zone))).isoformat()
    except (ValueError,KeyError): return None


def bounds(event):
    def get(instant,day,exclusive=False):
        value=timestamp(event.get(instant))
        if value: return datetime.fromisoformat(value)
        d=iso_day(event.get(day))
        if not d: return None
        parsed=date.fromisoformat(d)+(timedelta(days=1) if exclusive else timedelta())
        return datetime.combine(parsed,time(),BAKU)
    return get('start_at','start_date'), get('end_at','end_date',True) or get('end_at','start_date',True)


def lifecycle(event,now=None):
    now=now or datetime.now(timezone.utc)
    start,end=bounds(event)
    if end and end<=now: return 'archived'
    if start and start<=now: return 'ongoing'
    return 'upcoming' if start else 'unknown'


def explicit_dates(text,publication_year=None):
    found=[]
    for sentence in re.split(r'(?<=[.!?])\s+|\n',text):
        if not EVENT_DATE.search(sentence) or DEADLINE.search(sentence): continue
        years=re.findall(r'\b(20\d{2})\b',sentence)
        year=int(years[0]) if len(set(years))==1 else publication_year if not years and re.search(r'this year|bu il|этом году',sentence,re.I) else None
        # Never attach the article's year without an explicit relative-year reference.
        numeric=re.search(r'\b(20\d{2}-\d{2}-\d{2})(?:\s*(?:–|−|—|to|до|-)\s*(20\d{2}-\d{2}-\d{2}))?\b',sentence)
        if not year and not numeric: continue
        en=re.search(rf'\b({MONTH})\s+(\d{{1,2}})\b(?:\s*[–−-]\s*(\d{{1,2}})\b)?',sentence,re.I)
        az=re.search(rf'\b(\d{{1,2}})(?:\s*[–−-]\s*(\d{{1,2}}))?\s+({MONTH})\b',sentence,re.I)
        try:
            if numeric: first=date.fromisoformat(numeric[1]);last=date.fromisoformat(numeric[2]) if numeric[2] else None
            elif en: first=date(year,MONTHS[en[1].lower()],int(en[2]));last=date(year,first.month,int(en[3])) if en[3] else None
            elif az: first=date(year,MONTHS[az[3].lower()],int(az[1]));last=date(year,first.month,int(az[2])) if az[2] else None
            else: continue
            if last and last<first: continue
            found.append((first.isoformat(),last.isoformat() if last else None,sentence.strip()))
        except ValueError: continue
    identities={(a,b) for a,b,_ in found}
    return found[0] if len(identities)==1 else (None,None,None)
