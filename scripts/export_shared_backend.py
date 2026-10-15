"""Create a shareable allowlisted source/runtime archive without operational secrets."""
import json,tarfile
from pathlib import Path
from hashlib import sha256
ROOT=Path(__file__).resolve().parents[1]
def run():
    files=[]
    for folder in ('app','alembic','tests','scripts','deploy'):
        files.extend(p for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix in {'.py','.ini'} or p.is_file() and p.name=='Caddyfile')
    for name in ('requirements.txt','alembic.ini','Dockerfile','.dockerignore','docker-compose.production.yml','parts_index.json','manuals_index.json','.env.example','deploy/production.env.example','.github/ISSUE_TEMPLATE/backend_task.yml','.github/pull_request_template.md'):
        p=ROOT/name
        if p.exists():files.append(p)
    files.extend((ROOT/'data/organized').glob('*.json'))
    files.extend((ROOT/'data/verification').glob('*.json'))
    files.extend(p for p in (ROOT/'catalog-bundle').glob('*') if p.is_file())
    for name in ('MUSE_PROJECT_BRIEF.md','MUSE_SHARED_BACKEND.md','SHARED_BACKEND_DEPLOYMENT.md','DIGITALOCEAN_SETUP.md','FREESTYLE_BACKEND.md','VIPER3_BACKEND_PILOT.md'):
        files.append(ROOT/'docs'/name)
    files=sorted(set(files));output=ROOT/'artifacts';output.mkdir(exist_ok=True);archive=output/'mycoke-shared-backend.tar.gz'
    with tarfile.open(archive,'w:gz') as tar:
        for file in files:
            rel=file.relative_to(ROOT)
            if any(s in rel.parts for s in ('uploads','.git','.venv','node_modules','__pycache__')) or file.suffix in {'.db','.sqlite','.html'}:raise ValueError('Disallowed file')
            tar.add(file,arcname=str(rel),recursive=False)
    manifest={'archive':archive.name,'sha256':sha256(archive.read_bytes()).hexdigest(),'bytes':archive.stat().st_size,'file_count':len(files),'paths':[str(p.relative_to(ROOT)) for p in files],'excluded':['operational databases','uploads','real environment files','tokens','HTML snapshots','frontend build/dependencies']}
    (output/'shared-backend-manifest.json').write_text(json.dumps(manifest,indent=2));print({k:v for k,v in manifest.items() if k!='paths'})
if __name__=='__main__':run()
