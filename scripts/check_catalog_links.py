"""Targeted read-only checks, not a resumed full scan."""
import asyncio
import csv
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import httpx

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'data' / 'verification'

async def run():
    OUT.mkdir(parents=True, exist_ok=True)
    rows = json.loads((ROOT / 'data/organized/parts_catalog.json').read_text())
    targets = {}
    for row in rows:
        if row['_organization']['classification'] in {'equipment','needs_classification'}:
            targets[row['_organization']['source_index']] = row
    with (ROOT / 'data/reviewed/priority_review.csv').open(encoding='utf-8-sig') as file:
        for issue in csv.DictReader(file):
            if issue['issue'] == 'number_not_in_source_path':
                targets[int(issue['source_index'])] = rows[int(issue['source_index'])]
    semaphore = asyncio.Semaphore(4)
    async with httpx.AsyncClient(timeout=15,follow_redirects=True) as client:
        async def check(index,row):
            url = row.get('page_url')
            result = {'source_index':index,'part_number':row['part_number'],'url':url,'checked_at':datetime.now(timezone.utc).isoformat()}
            async with semaphore:
                try:
                    response = await client.get(url)
                    body = response.content
                    result.update(status=response.status_code,final_url=str(response.url),content_type=response.headers.get('content-type',''),body_sha256=sha256(body).hexdigest())
                    if 'html' in result['content_type']:
                        (OUT / f'page_{index}.html').write_bytes(body)
                        result['evidence_file'] = f'page_{index}.html'
                except Exception as exc:
                    result.update(error=type(exc).__name__ + ': ' + str(exc))
            return result
        results = await asyncio.gather(*(check(i,r) for i,r in targets.items()))
    (OUT / 'link_checks.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
    from collections import Counter
    print('checked',len(results),dict(Counter(r.get('status',r.get('error','unknown').split(':')[0]) for r in results)))

if __name__ == '__main__':
    asyncio.run(run())
