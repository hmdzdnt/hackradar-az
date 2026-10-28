"""Bounded, robots-aware HTTPS access to explicitly configured public hosts."""
import asyncio
import ipaddress
import socket
import time
from urllib.parse import urlparse, urljoin
from urllib.robotparser import RobotFileParser
import httpx

USER_AGENT = 'HackRadarAZ/1.0 (+https://github.com/hackradar-az; public-event-discovery)'
MAX_BYTES = 2_000_000


def safe_url(url, hosts):
    p = urlparse(url)
    if p.scheme != 'https' or p.hostname not in hosts or p.username or p.password or p.port not in (None, 443):
        raise ValueError('URL outside configured HTTPS source hosts')
    addresses = socket.getaddrinfo(p.hostname, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError('Non-public destination rejected')
    return url


class Fetcher:
    def __init__(self, hosts):
        self.hosts = set(hosts)
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(20, connect=8), headers={'User-Agent': USER_AGENT}, follow_redirects=False)
        self.robots = {}
        self.last = {}

    async def close(self):
        await self.client.aclose()

    async def validate(self, url):
        for attempt in range(3):
            try:
                return safe_url(url,self.hosts)
            except (socket.gaierror,TimeoutError):
                if attempt == 2:
                    raise
                await asyncio.sleep(2 ** attempt)

    async def raw(self, url):
        for redirect in range(4):
            await self.validate(url)
            host = urlparse(url).hostname
            origin = f'https://{urlparse(url).netloc}'
            policy = self.robots.get(origin)
            if redirect and (not policy or not policy.can_fetch(USER_AGENT,url)):
                raise PermissionError('Redirect target has no established robots permission')
            await asyncio.sleep(max(0, 1.2 - (time.monotonic() - self.last.get(host, 0))))
            self.last[host] = time.monotonic()
            for attempt in range(3):
                try:
                    async with self.client.stream('GET', url) as r:
                        if r.status_code in (301, 302, 303, 307, 308):
                            url = urljoin(url, r.headers.get('location', ''))
                            break
                        if r.status_code in (429, 401, 403):
                            raise PermissionError(f'Access restriction: {r.status_code}')
                        r.raise_for_status()
                        chunks, size = [], 0
                        async for chunk in r.aiter_bytes():
                            size += len(chunk)
                            if size > MAX_BYTES:
                                raise ValueError('Source exceeds size limit')
                            chunks.append(chunk)
                        return b''.join(chunks).decode(r.encoding or 'utf-8', errors='replace'), url
                except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as e:
                    if attempt == 2 or (isinstance(e, httpx.HTTPStatusError) and e.response.status_code < 500):
                        raise
                    await asyncio.sleep(2 ** attempt)
            else:
                raise RuntimeError('Fetch exhausted')
        raise ValueError('Too many redirects')

    async def get(self, url):
        await self.validate(url)
        p = urlparse(url)
        origin = f'{p.scheme}://{p.netloc}'
        if origin not in self.robots:
            robot = RobotFileParser()
            try:
                content, _ = await self.raw(origin + '/robots.txt')
                robot.parse(content.splitlines())
            except httpx.HTTPStatusError as e:
                if e.response.status_code != 404:
                    raise PermissionError('Cannot establish robots policy') from e
                robot.parse([])
            self.robots[origin] = robot
        robot = self.robots[origin]
        if not robot.can_fetch(USER_AGENT, url):
            raise PermissionError('robots.txt disallows URL')
        delay = robot.crawl_delay(USER_AGENT) or robot.crawl_delay('*') or 0
        if delay > 30:
            raise PermissionError('Crawl delay exceeds scheduled request budget')
        await asyncio.sleep(max(0, delay - (time.monotonic() - self.last.get(p.hostname, 0))))
        text, final = await self.raw(url)
        # Redirected paths must also be allowed before returning content.
        if not robot.can_fetch(USER_AGENT, final):
            raise PermissionError('Redirected path disallowed')
        return text, final
