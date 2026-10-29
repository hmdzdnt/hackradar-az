import argparse
import asyncio
from collections import Counter
from datetime import datetime,timezone
import hashlib
import json
import logging
from pathlib import Path
from .connectors import discover,official_links
from .extract import extract_candidates,verify,duplicate,canonical_title
from .network import Fetcher,RequestBudget,BudgetExceeded
from .search import search_links,route_links,PLATFORM_POLICIES
from .store import Store,DatabaseError

log=logging.getLogger('hackradar')
COUNTS=('discovered','accepted','duplicate','expired','rejected','quarantined','written','write_errors','source_errors')

def emit(action,**data):log.info(json.dumps({'action':action,**data},ensure_ascii=False))

def diagnostic(exc):
    result={'error':type(exc).__name__}
    if isinstance(exc,DatabaseError):result.update(http_status=exc.status,database_code=exc.code,operation=str(exc))
    elif isinstance(exc,PermissionError):result['reason']=str(exc)[:180]
    elif hasattr(exc,'response'):result['http_status']=exc.response.status_code
    return result


def select_sources(sources,slot,keys=None):
    enabled=[s for s in sources if s.get('enabled',True)]
    if keys:return [s for s in enabled if s['key'] in keys]
    if len(enabled)<=8:return enabled
    start=(slot*8)%len(enabled)
    return [enabled[(start+i)%len(enabled)] for i in range(8)]


async def corroborate(event,content,sources,budget):
    for official_source,url in official_links(content,sources):
        verifier=Fetcher(official_source['hosts'],budget)
        try:
            async with asyncio.timeout(15):
                page,final=await verifier.get(url)
                for official in extract_candidates(page,final,official_source):
                    if verify(official,official_source):continue
                    if canonical_title(official['title']) not in canonical_title(event['title']):continue
                    if event.get('start_date') and event['start_date']!=official['start_date']:continue
                    official['announcement_url']=event['announcement_url']
                    official['evidence']['corroborated_announcement']=event['announcement_url']
                    return official,official_source,hashlib.sha256(page.encode()).hexdigest()
        except Exception as exc:
            event['evidence'].setdefault('corroboration_errors',[]).append(diagnostic(exc))
            emit('corroboration_error',url=url,**diagnostic(exc))
        finally:await verifier.close()
    return None


async def run(dry_run=False,output=None,sources=None,source_keys=None,max_requests=80):
    sources=sources if sources is not None else json.loads(Path(__file__).with_name('sources.json').read_text())
    slot=int(datetime.now(timezone.utc).timestamp())//21600
    budget=RequestBudget(max_requests)
    store=None if dry_run else Store()
    run_id=None;events=[];quarantine=[];errors=[];coverage=[];seen=[];totals=Counter({key:0 for key in COUNTS})
    try:
        if store:
            run_id=(await store.request('POST','discovery_runs',json={'status':'running'}))[0]['id']
            schema=await store.detect_schema()
            emit('schema',extended=schema,migration='002_discovery_quality.sql' if not schema else None)
        try:
            links,search_report=await search_links(slot)
            extra,uncovered=route_links(links,sources)
        except Exception as exc:
            extra={};uncovered=[];search_report={'status':'failed',**diagnostic(exc)}
        coverage.append({'key':'search','name':'Opt-in Brave Search API',**search_report,'unfetched_links':uncovered})
        selected=select_sources(sources,slot,source_keys)
        if source_keys and not selected:raise ValueError('No enabled source matches --source')
        if not source_keys and extra:
            priority=[s for s in sources if s.get('enabled',True) and s['key'] in extra]
            selected=list({s['key']:s for s in priority+selected}.values())[:8]
        selected_keys={s['key'] for s in selected}
        for source in sources:
            if source['key'] not in selected_keys:
                coverage.append({'key':source['key'],'name':source['name'],'status':'disabled' if not source.get('enabled',True) else 'deferred','reason':source.get('limitation') or 'Rotating eight-source budget'})
        for configured in selected:
            source={**configured,'seeds':list(dict.fromkeys(configured.get('seeds',[])+extra.get(configured['key'],[])))}
            counts=Counter({key:0 for key in COUNTS});pages=0;source_errors=[];fetcher=None;source_id=None
            report={'key':source['key'],'name':source['name'],'url':source['url'],'status':'working'}
            before=budget.used
            if before>=budget.limit or totals['discovered']>=40:
                report.update(status='deferred',reason='Global request/candidate budget exhausted');coverage.append(report);continue
            emit('source_start',key=source['key'],url=source['url'])
            try:
                fetcher=Fetcher(source['hosts'],budget)
                source_id=await store.source(source) if store else None
                async with asyncio.timeout(45):
                    async for url,content in discover(source,fetcher):
                        if isinstance(content,Exception):
                            problem={'url':url,**diagnostic(content)};source_errors.append(problem)
                            if isinstance(content,BudgetExceeded):break
                            continue
                        if counts['discovered']>=12 or totals['discovered']+counts['discovered']>=40:
                            report.update(status='limited',reason='Candidate budget reached');break
                        pages+=1
                        candidates=list(extract_candidates(content,url,source))
                        if not candidates:
                            counts['rejected']+=1;emit('page_rejected',key=source['key'],url=url,reason='No identifiable hackathon announcement');continue
                        for event in candidates:
                            if counts['discovered']>=12 or totals['discovered']+counts['discovered']>=40:
                                report.update(status='limited',reason='Candidate budget reached');break
                            counts['discovered']+=1
                            issues=verify(event,source)
                            persistence_source=source
                            content_hash=hashlib.sha256(content.encode()).hexdigest()
                            if not source.get('trusted'):
                                checked=await corroborate(event,content,sources,budget)
                                if checked:
                                    event,persistence_source,content_hash=checked
                                    issues=event['evidence']['review']['reasons']
                            decision=event['evidence']['review']['decision']
                            emit('candidate',key=source['key'],url=url,decision=decision,reasons=issues)
                            # Reposts/untrusted sources cannot be automatically published.
                            if decision=='rejected':counts['rejected']+=1;continue
                            prior=next((item for item in reversed(seen) if duplicate(event,item[0])),None)
                            if prior and (prior[0].get('published') or not event.get('published')):
                                counts['duplicate']+=1
                                if store and prior[1]:
                                    try:await store.link(prior[1],source_id,event['announcement_url'],content_hash)
                                    except Exception as exc:
                                        counts['write_errors']+=1;source_errors.append(diagnostic(exc))
                                continue
                            event['evidence']['discovered_via']=source['key']
                            if dry_run:
                                result={'status':decision,'created':False,'id':None}
                            else:
                                try:
                                    primary_id=source_id if persistence_source is source else await store.source(persistence_source)
                                    result=await store.save(event,primary_id,content_hash,announcement_source_id=source_id)
                                except Exception as exc:
                                    counts['write_errors']+=1
                                    problem={'url':url,**diagnostic(exc)};source_errors.append(problem);emit('write_error',key=source['key'],**problem);continue
                            seen.append((event,result.get('id')))
                            counts[result['status']]+=1
                            if not dry_run and result.get('id') and result['status'] not in ('expired','duplicate'):counts['written']+=1
                            if result['status']=='accepted':events.append(event)
                            elif result['status']=='quarantined':quarantine.append(event)
                            emit('candidate_result',key=source['key'],status=result['status'],created=result.get('created'),dry_run=dry_run)
                if store and pages:
                    await store.request('PATCH','sources',params={'id':'eq.'+source_id},json={'last_success_at':datetime.now(timezone.utc).isoformat()})
            except Exception as exc:
                if isinstance(exc,DatabaseError):counts['write_errors']+=1
                source_errors.append(diagnostic(exc))
            finally:
                if fetcher:
                    try:await fetcher.close()
                    except Exception as exc:source_errors.append(diagnostic(exc))
            counts['source_errors']=len(source_errors)
            if source_errors:
                report['status']='partial' if pages else 'failed'
                errors.extend({'source':source['url'],**problem} for problem in source_errors)
            report.update(pages=pages,requests=budget.used-before,counts=dict(counts),errors=source_errors)
            coverage.append(report);totals.update(counts);emit('source_complete',**report)
        usable=any(c.get('pages',0)>0 for c in coverage)
        failed=bool(totals['write_errors'] or (selected and not usable))
        status='failed' if failed else 'partial' if errors else 'success'
        if store:
            await store.request('POST','rpc/archive_expired',json={})
            payload={'status':status,'finished_at':datetime.now(timezone.utc).isoformat(),'discovered':totals['discovered'],'published':totals['accepted'],'errors':errors}
            if store.extended_schema:payload['summary']={'counts':dict(totals),'coverage':coverage,'http_requests':budget.used}
            await store.request('PATCH','discovery_runs',params={'id':'eq.'+run_id},json=payload)
        result={'dry_run':dry_run,'status':status,'events':events,'quarantine':quarantine,'errors':errors,'counts':dict(totals),'coverage':coverage,'http_requests':budget.used,'platform_limitations':PLATFORM_POLICIES}
        if output:
            target=Path(output);target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(result,ensure_ascii=False,indent=2))
        emit('complete',dry_run=dry_run,status=status,counts=dict(totals),http_requests=budget.used)
        return result
    except Exception as exc:
        emit('run_error',**diagnostic(exc))
        if store and run_id:
            try:await store.request('PATCH','discovery_runs',params={'id':'eq.'+run_id},json={'status':'failed','finished_at':datetime.now(timezone.utc).isoformat(),'errors':errors+[diagnostic(exc)]})
            except Exception:emit('run_log_unavailable')
        raise
    finally:
        if store:await store.close()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--dry-run',action='store_true')
    parser.add_argument('--output')
    parser.add_argument('--source',action='append',dest='source_keys',help='Reviewed source key; repeat for a targeted diagnostic')
    parser.add_argument('--max-requests',type=int,default=80)
    args=parser.parse_args();logging.basicConfig(level=logging.INFO,format='%(message)s')
    logging.getLogger('httpx').setLevel(logging.WARNING)  # Structured status diagnostics, never auth headers/provider URLs.
    result=asyncio.run(run(args.dry_run,args.output,source_keys=args.source_keys,max_requests=args.max_requests))
    if result['status']=='failed':raise SystemExit(1)

if __name__=='__main__':main()
