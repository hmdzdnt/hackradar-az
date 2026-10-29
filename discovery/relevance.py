"""An Azerbaijan mention or organizer address alone is never location evidence."""
import re

PLACES = r'Azerbaijan|Azərbaycan(?:da|ın)?|Азербайджан(?:е|а)?|Baku|Bakı|Баку|Sumqay[ıi]t|Сумгаит|G[əa]nc[əa]|Ganja|Гяндж[ае]|X[ıi]rdalan|Khirdalan|Şuşa|Shusha|Naxçıvan|Nakhchivan|Mingəçevir|Mingachevir|Lənkəran|Lankaran|Şəki|Sheki'
PLACE=re.compile(r'\b(?:'+PLACES+r')\b',re.I)
VENUE=re.compile(r'(?:venue|location|məkan|ünvan|yer|место проведения|адрес)\s*[:：–-]\s*([^\n]{1,180})',re.I)
HOSTED=re.compile(r'(?:held|take place|hosted|состоится|пройд[её]т)[^\n.!?]{0,70}?(?:\bin\b|\bat\b|\bв\b)\s+(?:the\s+)?(?:'+PLACES+r')\b|(?:'+PLACES+r')(?: şəhərində| şəhəri|da|də)[^\n.!?]{0,70}?(?:keçiriləcək|baş tutacaq)',re.I)
ELIGIBLE=re.compile(
 r'(?:(?:open (?:only |exclusively )?to|exclusively for|eligible participants:?)\s+(?:participants|students|teams|residents)(?:\s+(?:based|living|located|studying))?\s+(?:in|from)\s+(?:'+PLACES+r')\b'
 r'|for participants (?:based|living) in\s+(?:'+PLACES+r')\b'
 r'|for Azerbaijan-based (?:participants|students|teams)'
 r'|Azərbaycan(?:da|ın)[^\n.!?]{0,60}?(?:yaşayan|təhsil alan)[^\n.!?]{0,60}?iştirakçı'
 r'|для (?:участников|жителей|студентов) (?:из|проживающих в)\s+(?:'+PLACES+r')\b)',re.I)
CITY_ALIASES={'baku':'Bakı','bakı':'Bakı','баку':'Bakı','ganja':'Gəncə','gəncə':'Gəncə','sumqayıt':'Sumqayıt','khirdalan':'Xırdalan','xırdalan':'Xırdalan'}


def location_evidence(data,text,source):
    location=data.get('location') if data else None
    if isinstance(location,list):
        location=next((x for x in location if isinstance(x,dict) and x.get('@type')!='VirtualLocation'),None)
    if isinstance(location,dict):
        address=location.get('address')
        country=address.get('addressCountry') if isinstance(address,dict) else None
        if isinstance(country,dict):country=country.get('name') or country.get('identifier')
        city=address.get('addressLocality') if isinstance(address,dict) else None
        place=' '.join(str(x or '') for x in [location.get('name'),address if isinstance(address,str) else '',city,country])
        if country and str(country).casefold() not in ('az','aze','azerbaijan','azərbaycan','азербайджан'):
            return None,None,None  # A named foreign venue overrides incidental Baku mentions.
        if str(country or '').casefold() in ('az','aze') or PLACE.search(place):
            return {'kind':'physical_location','quote':place[:400]},CITY_ALIASES.get(str(city).casefold(),city),place[:400]
    for line in text.splitlines():
        venue=VENUE.search(line)
        hosted=HOSTED.search(line)
        quote=venue[0].split(';',1)[0] if venue else hosted[0] if hosted else None
        if quote and PLACE.search(re.sub(r'\([^)]*\)','',quote)):
            match=PLACE.search(quote)[0]
            return {'kind':'physical_location','quote':quote},CITY_ALIASES.get(match.casefold()),quote
        eligibility=ELIGIBLE.search(line)
        if eligibility and PLACE.search(eligibility[0]):
            return {'kind':'explicit_participant_eligibility','quote':eligibility[0]},None,None
    # Reviewed venue adapters: exact local name must be connected to hosting language.
    for venue,city in source.get('local_venues',{}).items():
        match=re.search(r'(?:held|take place|hosted|keçiriləcək).{0,60}?\bat\s+'+re.escape(venue)+r'\b',text,re.I)
        if match:return {'kind':'physical_location','quote':match[0],'reviewed_venue':venue},city,venue
    return None,None,None
