import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
from .connectors import discover
from .extract import extract, verify, duplicate
from .network import Fetcher
from .store import Store

log = logging.getLogger('hackradar')

def emit(action, **data):
    log.info(json.dumps({'action':action,**data},ensure_ascii=False))


async def run(dry_run=False, output=None):
    sources = json.loads(Path(__file__).with_name('sources.json').read_text())
    store = None if dry_run else Store()
    run_id, events, errors = None, [], []
    try:
        if store:
            run_id = (await store.request('POST','discovery_runs',json={'status':'running'}))[0]['id']
        for source in sources:
            if source.get('enabled',True) is False:
                continue
            fetcher = Fetcher(source['hosts'])
            try:
                source_id = await store.source(source) if store else None
                async with asyncio.timeout(180):
                    async for url, content in discover(source,fetcher):
                        if isinstance(content,Exception):
                            errors.append({'source':url,'error':type(content).__name__})
                            continue
                        event = extract(content,url,source)
                        if not event:
                            continue
                        problems = verify(event,source)
                        emit('candidate',url=url,published=event['published'],issues=problems)
                        if any(duplicate(event,e) for e in events):
                            continue
                        events.append(event)
                        if store:
                            await store.save(event,source_id,hashlib.sha256(content.encode()).hexdigest())
                if store:
                    await store.request('PATCH','sources',params={'id':'eq.'+source_id},json={'last_success_at':datetime.now(timezone.utc).isoformat()})
            except Exception as e:
                errors.append({'source':source['url'],'error':type(e).__name__})
                emit('source_error',source=source['url'],error=type(e).__name__)
            finally:
                await fetcher.close()
        published = [e for e in events if e['published']]
        if store:
            await store.request('POST','rpc/archive_expired',json={})
            await store.request('PATCH','discovery_runs',params={'id':'eq.'+run_id},json={'status':'partial' if errors else 'success','finished_at':datetime.now(timezone.utc).isoformat(),'discovered':len(events),'published':len(published),'errors':errors})
        if output:
            target = Path(output)
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_text(json.dumps({'dry_run':dry_run,'events':events,'errors':errors},ensure_ascii=False,indent=2))
        emit('complete',dry_run=dry_run,discovered=len(events),published=len(published),errors=errors)
        return {'events':events,'errors':errors}
    except Exception as e:
        emit('run_error',error=type(e).__name__)
        if store and run_id:
            try:
                await store.request('PATCH','discovery_runs',params={'id':'eq.'+run_id},json={'status':'failed','finished_at':datetime.now(timezone.utc).isoformat(),'errors':errors+[{'error':type(e).__name__}]})
            except Exception:
                emit('run_log_unavailable')
        raise
    finally:
        if store:
            await store.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run',action='store_true',help='Verify real sources without database writes')
    parser.add_argument('--output',help='Write a private diagnostic report (never frontend seed data)')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO,format='%(message)s')
    result = asyncio.run(run(args.dry_run,args.output))
    # A wholly broken run must fail CI rather than produce a false success.
    if result['errors'] and not result['events']:
        raise SystemExit(1)

if __name__ == '__main__':
    main()
