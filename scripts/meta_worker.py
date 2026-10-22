"""Local simulation worker only; no live service or Graph credential loading."""
import argparse
import json
import os
import signal
import time
import uuid
from pathlib import Path

import httpx
from app.integrations.meta_whatsapp import Bridge
from app.integrations.meta_runtime import Operations, Worker, restore


class SyntheticAdapter:
    def post(self, path, *, content, headers):
        message=json.loads(content)
        if message['sender_id']!='15550000001' or message['action']!='query':
            return httpx.Response(403)
        return httpx.Response(200,json={'reply_to':{'provider_id':'simulation','recipient_id':message['sender_id'],
                            'chat_type':'individual'},'data':{'simulation_only':True,'user_id':2,'organization_id':1}})


class SyntheticSender:
    def send(self, payload, *, key):
        return 'simulation-receipt-'+key


def simulation_bridge(path):
    # Explicit profile in a private, newly initialized sandbox. No implicit production path.
    if not Path(path).is_file():
        raise ValueError('Initialize a new simulation database first')
    import sqlite3
    with sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True) as db:
        row=db.execute("SELECT value FROM simulation_profile WHERE name='mode'").fetchone()
        if not row or row[0]!='simulation-only-v1':
            raise ValueError('Not a simulation state file')
    return Bridge(state_path=path,adapter=SyntheticAdapter(),sender=SyntheticSender(),
                  channel_secret='simulation-only-worker-secret-'+('x'*32))


def initialize(path):
    target=Path(path)
    fd=os.open(target,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
    from app.integrations.meta_whatsapp import StateStore
    with StateStore(path).transaction() as db:
        db.execute('CREATE TABLE simulation_profile(name TEXT PRIMARY KEY,value TEXT NOT NULL)')
        db.execute("INSERT INTO simulation_profile VALUES('mode','simulation-only-v1')")
    bridge=simulation_bridge(path)
    bridge.accept([{'id':'simulation-'+uuid.uuid4().hex,'sender':'15550000001','text':'我的身份','timestamp':int(time.time())}])
    Operations(path)
    return {'initialized':True,'simulation_only':True}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['init','start','stop','monitor','backup','restore','cleanup'])
    parser.add_argument('--state',required=True)
    parser.add_argument('--simulation',action='store_true')
    parser.add_argument('--cycles',type=int)
    parser.add_argument('--destination')
    parser.add_argument('--backup')
    parser.add_argument('--sha256',default='')
    parser.add_argument('--operator',default='')
    parser.add_argument('--retention-days',type=int,default=30)
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--confirmation',default='')
    args=parser.parse_args(argv)
    try:
        if args.command=='init':
            if not args.simulation:raise ValueError('Explicit --simulation required')
            result=initialize(args.state)
        elif args.command=='start':
            if not args.simulation:raise ValueError('Only --simulation startup is implemented')
            if args.cycles is not None and args.cycles<1:raise ValueError('Cycles must be positive')
            worker=Worker(simulation_bridge(args.state))
            previous={s:signal.signal(s,worker.request_stop) for s in (signal.SIGTERM,signal.SIGINT)}
            try:result=worker.run(max_cycles=args.cycles)
            finally:
                for s,handler in previous.items():signal.signal(s,handler)
        elif args.command=='restore':
            if not args.backup:raise ValueError('Backup required')
            result=restore(args.backup,args.state,sha256=args.sha256)
        else:
            ops=Operations(args.state)
            if args.command=='stop':result=ops.stop()
            elif args.command=='monitor':result=ops.monitor()
            elif args.command=='backup':
                if not args.destination:raise ValueError('New backup destination required')
                result=ops.backup(args.destination,operator=args.operator)
            elif not args.apply:result=ops.cleanup_plan(args.retention_days)
            else:
                if not args.backup:raise ValueError('New backup path required before cleanup')
                result=ops.cleanup(retention_days=args.retention_days,confirmation=args.confirmation,
                                   backup_path=args.backup,operator=args.operator)
        print(json.dumps(result,ensure_ascii=False,indent=2))
    except (ValueError,OSError,__import__('sqlite3').Error) as exc:
        parser.error(str(exc))


if __name__=='__main__':
    main()
