"""Package the five public Quest runtime datasets as an additive catalog bundle."""
import base64,gzip,hashlib,io,json,tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
FILES=['data/organized/quest_added_parts.json','data/organized/quest_added_manifest.json','data/organized/quest_graph.json','data/organized/quest_parts_catalog.json','data/verification/quest_new_official_parts.json']
def build():
    buffer=io.BytesIO();inventory=[]
    with gzip.GzipFile(fileobj=buffer,mode='wb',mtime=0,filename='') as gz:
        with tarfile.open(fileobj=gz,mode='w') as tar:
            for name in FILES:
                data=(ROOT/name).read_bytes();member=tarfile.TarInfo(name);member.size=len(data);member.mode=0o644
                tar.addfile(member,io.BytesIO(data));inventory.append({'path':name,'sha256':hashlib.sha256(data).hexdigest()})
    data=buffer.getvalue();encoded=base64.b64encode(data);out=ROOT/'catalog-bundle/quest';out.mkdir(exist_ok=True)
    (out/'catalog-000.b64').write_bytes(encoded)
    (out/'manifest.json').write_text(json.dumps({'archive_sha256':hashlib.sha256(data).hexdigest(),'chunks':[{'name':'catalog-000.b64','sha256':hashlib.sha256(encoded).hexdigest()}],'files':inventory},indent=2))
    print({'files':len(FILES),'encoded_bytes':len(encoded)})
if __name__=='__main__':build()
