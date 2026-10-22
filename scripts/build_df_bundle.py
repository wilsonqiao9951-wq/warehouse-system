"""Package the five public DF runtime datasets as an additive catalog bundle."""
import base64,gzip,hashlib,io,json,tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
FILES=['data/organized/df_added_parts.json','data/organized/df_added_manifest.json','data/organized/df_graph.json','data/organized/df_parts_catalog.json','data/verification/df_new_official_parts.json']
def build():
    buffer=io.BytesIO();inventory=[]
    with gzip.GzipFile(fileobj=buffer,mode='wb',mtime=0,filename='') as gz:
        with tarfile.open(fileobj=gz,mode='w') as tar:
            for name in FILES:
                data=(ROOT/name).read_bytes();member=tarfile.TarInfo(name);member.size=len(data);member.mode=0o644
                tar.addfile(member,io.BytesIO(data));inventory.append({'path':name,'sha256':hashlib.sha256(data).hexdigest()})
    data=buffer.getvalue();out=ROOT/'catalog-bundle/df';out.mkdir(exist_ok=True);chunks=[]
    for offset in range(0,len(data),576*1024):
        encoded=base64.b64encode(data[offset:offset+576*1024]);name=f'catalog-{len(chunks):03d}.b64'
        (out/name).write_bytes(encoded);chunks.append({'name':name,'sha256':hashlib.sha256(encoded).hexdigest()})
    (out/'manifest.json').write_text(json.dumps({'archive_sha256':hashlib.sha256(data).hexdigest(),'chunks':chunks,'files':inventory},indent=2))
    print({'files':len(FILES),'chunks':len(chunks),'archive_bytes':len(data)})
if __name__=='__main__':build()
