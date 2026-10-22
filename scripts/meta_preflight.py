"""Offline, read-only preparation checks. Never activates or contacts a service."""
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import time
from app.integrations.meta_production import configuration


def backups_valid(manifest):
    path=Path(manifest)
    if not path.is_absolute() or path.is_symlink() or path.stat().st_size>65536:
        return False
    data=json.loads(path.read_text())
    if not 0<=time.time()-data['created_at']<=86400:return False
    entries=data['files']
    if {e['kind'] for e in entries}!={'business','adapter','bridge','uploads'} or len(entries)!=4:return False
    paths=set()
    for entry in entries:
        p=Path(entry['path'])
        if not p.is_absolute() or p.resolve()!=p or p in paths:return False
        paths.add(p)
        fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        try:
            info=os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or not info.st_size or stat.S_IMODE(info.st_mode)&0o077:return False
            digest=hashlib.sha256()
            with os.fdopen(os.dup(fd),'rb') as stream:
                for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
            if digest.hexdigest()!=entry['sha256']:return False
        finally:os.close(fd)
    return True


def report():
    checks={}
    checks['activation_disabled']=all(os.getenv(k,'false')=='false' for k in
                                     ('META_CHANNEL_ENABLED','META_LIVE_SEND_ENABLED','WHATSAPP_ADAPTER_ENABLED'))
    checks['production_mode']=os.getenv('META_DEPLOYMENT_MODE')=='production'
    config=None
    try:
        config=configuration('check');checks['configuration']=True
    except Exception:checks['configuration']=False
    checks['image_pinned']=bool(re.fullmatch(r'[a-zA-Z0-9./:_-]+@sha256:[0-9a-f]{64}',os.getenv('META_IMAGE_REF','')))
    checks['pilot_registry']=False
    if config:
        try:
            path=config['adapter_state']
            with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:
                checks['pilot_registry']=db.execute('SELECT COUNT(*) FROM pilot_members WHERE active=1 AND expires>?',(time.time(),)).fetchone()[0]>0
        except (OSError,sqlite3.Error):pass
    try:checks['backup_files_verified']=backups_valid(os.environ['META_BACKUP_MANIFEST'])
    except Exception:checks['backup_files_verified']=False
    return {'offline_checks_passed':all(checks.values()),'checks':checks,'services_started':False,
            'live_send_enabled':False,'production_activation_authorized':False,
            'not_verified':['account_authorization','live_database_identity','image_registry_digest',
                            'backup_restore_consistency','public_tls','official_sandbox','pilot_user_directory']}


def main():
    result=report();print(json.dumps(result,sort_keys=True))
    return 0 if result['offline_checks_passed'] else 1


if __name__=='__main__':
    raise SystemExit(main())
