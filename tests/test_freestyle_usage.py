import pytest
from sqlalchemy import select,func
from app.models import Organization,Part,Warehouse,Equipment,WorkOrder,WorkOrderPart,PartMachineAssociation,User,UserRole,AuditLog
from app.core.config import settings
from app.services.freestyle_chain import graph,matches_model


@pytest.mark.parametrize('mid',['3100','4000','7000','7100','8000','8100','9000','9100'])
def test_usage_and_verification_are_scoped_to_exact_model_and_organization(client,mid):
    name=graph()['models'][mid]['official_model'];other=next(k for k in graph()['models'] if k!=mid)
    assert matches_model(name,mid) and matches_model('Freestyle '+mid,mid) and matches_model(mid,mid)
    assert not matches_model(other,mid) and not matches_model(mid+'/'+other,mid)
    p=client.post('/api/parts',json={'part_number':'USE-'+mid,'name':'Usage only'}).json();pid=p['id']
    with client.app.state.testing_session_local() as db:
        db.add(Organization(id=2,name='Other',slug='other'));db.flush()
        w=Warehouse(organization_id=1,code='W',name='Main');fw=Warehouse(organization_id=2,code='F',name='Foreign')
        asset=Equipment(organization_id=1,model=name);conflict=Equipment(organization_id=1,model=other);fa=Equipment(organization_id=2,model=name)
        fp=Part(organization_id=2,part_number=p['part_number'],name='Foreign');db.add_all([w,fw,asset,conflict,fa,fp]);db.flush();fid=fp.id
        cases=[('GOOD',name,None,1,pid,w.id,'yes'),('ASSET',None,asset.id,1,pid,w.id,'yes'),('NOT-INSTALLED',mid,None,1,pid,w.id,'no'),('OTHER',other,None,1,pid,w.id,'yes'),('CONFLICT',name,conflict.id,1,pid,w.id,'yes'),('REVERSE',other,asset.id,1,pid,w.id,'yes'),('FOREIGN-EQUIP',name,fa.id,1,pid,w.id,'yes'),('FOREIGN-ORDER',name,None,2,pid,w.id,'yes'),('FOREIGN-PART',name,None,1,fid,w.id,'yes'),('FOREIGN-WH',name,None,1,pid,fw.id,'yes'),('RANGE',mid+'/'+other,None,1,pid,w.id,'yes')]
        for ticket,model,eid,org,part,wh,installed in cases:
            order=WorkOrder(organization_id=org,ticket_number=ticket,machine_type=model,equipment_id=eid);db.add(order);db.flush()
            db.add(WorkOrderPart(organization_id=1,work_order_id=order.id,part_id=part,warehouse_id=wh,quantity=2,installed=installed))
        db.add(PartMachineAssociation(organization_id=1,part_id=pid,machine_model=name,recognition_source='employee_photo'))
        db.add(PartMachineAssociation(organization_id=1,part_id=pid,machine_model=graph()['models'][other]['official_model'],recognition_source='field_verified'))
        db.add(PartMachineAssociation(organization_id=2,part_id=fid,machine_model=name,recognition_source='field_verified'));db.commit()
    base='/api/catalog/freestyle/models/'+mid
    row=client.get(base+'/parts',params={'q':p['part_number']}).json()['items'][0]
    assert row['official_associations']==[] and row['cross_model_compatibility_confirmed'] is False
    assert len(row['field_associations'])==1 and row['field_associations'][0]['source']=='field_observation'
    assert row['work_order_usage']['material_record_count']==3 and row['work_order_usage']['actual_usage_count']==2 and row['work_order_usage']['actual_used_quantity']==4
    assert {r['ticket_number'] for r in row['work_order_usage']['records']}=={'GOOD','ASSET','NOT-INSTALLED'}
    section=graph()['models'][mid]['sections'][0]['id']
    assert client.get(base+'/parts',params={'q':p['part_number'],'section_id':section}).json()['total']==0
    detail=client.get(base+f'/parts/{pid}/usage',params={'skip':1,'limit':1}).json();assert detail['total']==3 and len(detail['items'])==1
    assert client.get(base+f'/parts/{fid}/usage').status_code==404
    assert client.post(base+'/field-verifications',json={'part_id':fid}).status_code==404
    result=client.post(base+'/field-verifications',json={'part_id':pid});assert result.status_code==200 and result.json()['confirmed_count']==1
    row=client.get(base+'/parts',params={'q':p['part_number']}).json()['items'][0]
    assert row['field_associations'][0]['source']=='field_verified' and row['official_associations']==[]
    assert row['work_order_usage']['compatibility_confirmed'] is False


def test_freestyle_verification_permission_audit_and_official_relation_preserved(client):
    mid='9100';cid=graph()['models'][mid]['part_ids'][0]
    p=client.post(f'/api/catalog/parts/{cid}/import').json()
    with client.app.state.testing_session_local() as db:
        engineer=User(organization_id=1,name='Engineer',email='e@example.invalid',role=UserRole.ENGINEER,is_active=True)
        warehouse=User(organization_id=1,name='Warehouse',email='w@example.invalid',role=UserRole.WAREHOUSE,is_active=True);db.add_all([engineer,warehouse]);db.commit();eid,wid=engineer.id,warehouse.id
    settings.rbac_enforce=True
    try:
        base='/api/catalog/freestyle/models/'+mid
        assert client.get(base+f"/parts/{p['id']}/usage").status_code==401
        assert client.post(base+'/field-verifications',json={'part_id':p['id']},headers={'X-User-Id':str(wid)}).status_code==403
        for count in (1,2):
            r=client.post(base+'/field-verifications',json={'part_id':p['id']},headers={'X-User-Id':str(eid)})
            assert r.status_code==200 and r.json()['confirmed_count']==count
        row=client.get(base+'/parts',params={'q':p['part_number']},headers={'X-User-Id':str(eid)}).json()['items'][0]
        assert row['official_associations'] and row['field_associations'][0]['source']=='field_verified'
        assert row['work_order_usage']['actual_usage_count']==0 and row['cross_model_compatibility_confirmed'] is False
        with client.app.state.testing_session_local() as db:
            logs=list(db.scalars(select(AuditLog).where(AuditLog.action=='verify_freestyle_part')));assert len(logs)==2 and all(a.user_id==eid for a in logs)
    finally:settings.rbac_enforce=False


def test_photo_observation_does_not_increment_explicit_verification(client):
    p=client.post('/api/parts',json={'part_number':'CONFIRM-ONLY','name':'Confirm'}).json()
    first=client.post('/api/catalog/freestyle/models/8000/field-verifications',json={'part_id':p['id']}).json()
    response=client.post('/api/parts/recognition/observations',data={'part_id':str(p['id']),'machine_model':'8000 Crew-Serve'})
    assert response.status_code==200 and response.json()['confirmed_count']==first['confirmed_count']
    row=client.get('/api/catalog/freestyle/models/8000/parts',params={'q':'CONFIRM-ONLY'}).json()['items'][0]
    assert row['field_associations'][0]['source']=='field_verified' and row['work_order_usage']['actual_usage_count']==0
