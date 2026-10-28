"""Export only actually verified live discoveries; fixtures cannot enter this path."""
import json
from datetime import datetime,timezone
from pathlib import Path
import sys
from uuid import uuid5,NAMESPACE_URL

report=json.loads(Path(sys.argv[1]).read_text())
if report.get('errors'):
    raise SystemExit('Partial discovery run; existing snapshot was not replaced.')
fields='title organizer description city format start_date end_date registration_deadline registration_url official_source_url age_min age_max age_restrictions team_requirements prize_info has_prize topics registration_status archived last_verified_at'.split()
events=[]
for e in report['events']:
    if not (e.get('published') and e.get('verified') and e.get('last_verified_at') and e.get('evidence')):
        continue
    row={k:e.get(k) for k in fields}
    row['id']=str(uuid5(NAMESPACE_URL,e['official_source_url']))
    events.append(row)
if not events:
    raise SystemExit('No verified real events; existing snapshot was not replaced.')
Path('public/events.json').write_text(json.dumps({'events':events,'verifiedAt':max(e['last_verified_at'] for e in events),'mode':'verified-source-snapshot'},ensure_ascii=False,indent=2)+'\n')
print(f'Exported {len(events)} source-verified event(s); no private evidence or write keys included.')
