"""Execute the exact shareable request/expectation fixture against isolated data."""
import json
from pathlib import Path
from sqlalchemy import select,func
from app.models import RepairCaseReport,AuditLog
from test_whatsapp_adapter import setup,send,SECRET

def test_shareable_simulation_kit(setup):
    api,admin,ids,orders,_,factory,_=setup
    variables={'tech_id':ids[1],'own_order_id':orders[0],'foreign_order_id':orders[1]}
    suite=json.loads((Path(__file__).parent/'fixtures/whatsapp_simulation.json').read_text())
    def resolve(x):
        if isinstance(x,dict):return {k:resolve(v) for k,v in x.items()}
        if isinstance(x,list):return [resolve(v) for v in x]
        if isinstance(x,str):
            if x.startswith('$') and x[1:] in variables:return variables[x[1:]]
            for key,value in variables.items():x=x.replace('$'+key,str(value))
        return x
    def at(obj,path):
        for key in path.split('.'):obj=obj[int(key)] if isinstance(obj,list) else obj[key]
        return obj
    for case in suite['cases']:
        if 'admin_invite' in case:r=api.post('/api/channels/whatsapp/bindings',json=resolve(case['admin_invite']),headers=admin)
        else:r=send(api,case['action'],resolve(case['arguments']),phone=case.get('phone',suite['sender_id']),eid=case.get('event_id',case['id']),text=resolve(case.get('text','')),secret='invalid' if case.get('invalid_signature') else SECRET)
        assert r.status_code==case['status'],(case['id'],r.text)
        data=r.json()
        for path,value in case.get('expect',{}).items():assert at(data,path)==resolve(value),(case['id'],path,data)
        for path,n in case.get('list_length',{}).items():assert len(at(data,path))==n
        for key,path in case.get('extract',{}).items():variables[key]=at(data,path)
        if 'reports_count' in case:
            with factory() as db:assert db.scalar(select(func.count()).select_from(RepairCaseReport))==case['reports_count']
    with factory() as db:assert db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action=='submit_repair_case'))==1
