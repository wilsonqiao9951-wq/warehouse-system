"""Preserve manufacturer-site discovery independently of reviewed myCoke part links."""
import asyncio,json,re
from hashlib import sha256
from datetime import datetime,timezone
from urllib.parse import urljoin,urlparse,urldefrag
from html.parser import HTMLParser
from pathlib import Path
import httpx
ROOT=Path(__file__).resolve().parents[1]
BASE='https://www.multiplexbeverage.com'
class Links(HTMLParser):
    def __init__(self):super().__init__();self.links=[];self.href=None;self.label=''
    def handle_starttag(self,tag,attrs):
        if tag=='a':self.href=dict(attrs).get('href');self.label=''
    def handle_data(self,data):
        if self.href:self.label+=data
    def handle_endtag(self,tag):
        if tag=='a' and self.href:self.links.append((self.href,self.label.strip()));self.href=None
async def run():
    dest=ROOT/'data/verification/multiplex_brand_20261018';dest.mkdir(exist_ok=True)
    prior=json.loads((ROOT/'data/verification/multiplex_brand_discovery.json').read_text()) if (ROOT/'data/verification/multiplex_brand_discovery.json').exists() else {'pages':[]}
    statuses={e['url']:e.get('http_status') for e in prior['pages']}
    queue=[BASE+'/Products',BASE+'/QRCodes/FreshBlender',BASE+'/QRCodes/Blend-In-Cup/BIC-Manual-Fill',BASE+'/QRCodes/Blend-In-Cup/BIC-IOB'];seen=set();pages=[];docs=[]
    async with httpx.AsyncClient(timeout=25,follow_redirects=True) as c:
        while queue and len(seen)<80:
            url=queue.pop(0)
            if url in seen:continue
            seen.add(url)
            e={'url':url,'checked_at':datetime.now(timezone.utc).isoformat()}
            try:
                file=sha256(url.encode()).hexdigest()+'.html'
                if (dest/file).exists() and statuses.get(url)==200:r=httpx.Response(200,content=(dest/file).read_bytes(),request=httpx.Request('GET',url))
                else:r=await c.get(url);(dest/file).write_bytes(r.content)
                e.update(http_status=r.status_code,final_url=str(r.url),body_sha256=sha256(r.content).hexdigest(),file=file)
                parser=Links();parser.feed(r.text);title=re.search(r'<title>(.*?)</title>',r.text,re.S);e['title']=title.group(1).strip() if title else None
                e['document_links']=[]
                for href,label in parser.links:
                    target=urldefrag(urljoin(str(r.url),href))[0];path=urlparse(target).path.lower()
                    if urlparse(target).netloc not in ('www.multiplexbeverage.com','direct.multiplexbeverage.com'):continue
                    if path.startswith('/getmedia/') or path.endswith('.pdf'):
                        row={'source_page':url,'url':target,'label':label,'status':'document_discovered_part_rows_not_reviewed'}
                        if row not in docs:docs.append(row)
                        e['document_links'].append(row)
                    if path.startswith(('/products/','/product/')) and target not in seen and target not in queue:queue.append(target)
                e['dynamic_listing']=bool('launchProductListing' in r.text)
            except httpx.HTTPError as exc:e['error']=type(exc).__name__
            pages.append(e)
    result={'scope':'Public manufacturer-site discovery; not a claim of exhaustive worldwide or historical model coverage.','review_status':'document_review_pending','pages':pages,'documents':docs,'unvisited_queue':queue}
    (ROOT/'data/verification/multiplex_brand_discovery.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print({'pages':len(pages),'document_links':len(docs),'unvisited':len(queue)})
if __name__=='__main__':asyncio.run(run())
