from urllib.parse import urlsplit,urlunsplit,parse_qsl,urlencode


def canonical_url(value):
    if not isinstance(value,str):return None
    try:
        p=urlsplit(value or '')
        if p.scheme!='https' or not p.hostname or p.username or p.password or p.port not in (None,443):return None
        query=[(k,v) for k,v in parse_qsl(p.query,keep_blank_values=True) if not k.lower().startswith('utm_') and k.lower() not in ('fbclid','gclid')]
        return urlunsplit(('https',p.hostname.lower(),p.path.rstrip('/') or '/',urlencode(sorted(query)),''))
    except ValueError:return None
