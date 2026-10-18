import json
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.rbac import Actor, get_current_actor, require_roles
from app.models import Part, UserRole
from app.schemas import PartRead
from app.services.catalog import entries, search

catalog_router = APIRouter(prefix="/catalog", tags=["myCoke catalog"])

@catalog_router.get("/parts")
def catalog_parts(q: str = Query(default="", max_length=200), skip: int = Query(default=0, ge=0),
                  limit: int = Query(default=25, ge=1, le=100), actor: Actor = Depends(get_current_actor)):
    return search("parts", q, skip, limit)

@catalog_router.get("/manuals")
def catalog_manuals(q: str = Query(default="", max_length=200), skip: int = Query(default=0, ge=0),
                    limit: int = Query(default=25, ge=1, le=100), actor: Actor = Depends(get_current_actor)):
    return search("manuals", q, skip, limit)

@catalog_router.get("/equipment")
def catalog_equipment(q: str = Query(default="", max_length=200), skip: int = Query(default=0, ge=0),
                      limit: int = Query(default=25, ge=1, le=100), actor: Actor = Depends(get_current_actor)):
    return search("equipment", q, skip, limit)

@catalog_router.post("/parts/{catalog_id}/import", response_model=PartRead)
def import_catalog_part(catalog_id: str, db: Session = Depends(get_db), actor: Actor = Depends(get_current_actor)):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER, UserRole.WAREHOUSE)
    row = next((row for row in entries("parts") if row["catalog_id"] == catalog_id), None)
    if row is None:
        raise HTTPException(status_code=404, detail="Catalog entry not found")
    number = str(row.get("part_number") or "").strip()
    name = str(row.get("name") or row.get("description") or "").strip()
    if not row.get("stock_import_candidate", False):
        raise HTTPException(status_code=422, detail="This catalog entry is not verified for stock import")
    if not number or len(number) > 120 or not name or len(name) > 255 or row.get("entry_type") in {"equipment", "manual", "test"}:
        raise HTTPException(status_code=422, detail="This entry needs review before adding as an inventory part")
    def existing():
        return db.scalar(select(Part).where(Part.organization_id == actor.organization_id, Part.part_number == number))
    found = existing()
    if found:
        return found
    models = row.get("fits_equipment_models") or []
    model_text = ", ".join(str(value) for value in models) if isinstance(models, list) else str(models)
    image = row.get("image_url")
    part = Part(organization_id=actor.organization_id, part_number=number, name=name,
                machine_type=model_text[:255] or None, supplier=str(row.get("manufacturer") or "")[:255] or None,
                image_url=image if isinstance(image, str) and len(image) <= 500 else None,
                custom_fields={"mycoke": dict(row)}, notes=str(row.get("description") or "") or None)
    db.add(part)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        found = existing()
        if found:
            return found
        raise
    db.refresh(part)
    return part


@catalog_router.get('/models/viper-3')
def viper3_model(actor: Actor = Depends(get_current_actor)):
    from app.services.model_chain import graph
    g=graph()
    return {'model_id':g['model_id'],'official_model':g['official_model'],'equipment':g['equipment'],'sections':g['sections'],'official_part_count':len({cid for s in g['sections'] for cid in s['part_ids']}),'policy':g['policy']}


@catalog_router.get('/models/viper-3/parts')
def viper3_parts(section_id: str | None = None,q: str = Query('',max_length=200),skip: int = Query(0,ge=0),limit: int = Query(25,ge=1,le=100),db: Session = Depends(get_db),actor: Actor = Depends(get_current_actor)):
    from app.services.model_chain import chain,graph
    if section_id is not None and not any(s['id']==section_id for s in graph()['sections']):
        raise HTTPException(404,'Viper 3 section not found')
    return chain(db,actor.organization_id,section_id,q,skip,limit)


from pydantic import BaseModel,Field
class Viper3FieldVerification(BaseModel):
    part_id: int = Field(gt=0)


@catalog_router.post('/models/viper-3/field-verifications')
def verify_viper3_part(payload: Viper3FieldVerification,db: Session = Depends(get_db),actor: Actor = Depends(get_current_actor)):
    from datetime import datetime,timezone
    from app.models import PartMachineAssociation,AuditLog
    from app.services.model_chain import MODEL
    require_roles(actor,UserRole.ADMIN,UserRole.MANAGER,UserRole.ENGINEER)
    part=db.scalar(select(Part).where(Part.id==payload.part_id,Part.organization_id==actor.organization_id))
    if not part:raise HTTPException(404,'Organization part not found')
    association=db.scalar(select(PartMachineAssociation).where(PartMachineAssociation.organization_id==actor.organization_id,PartMachineAssociation.part_id==part.id,PartMachineAssociation.machine_model==MODEL))
    if association:
        association.confirmed_count=association.confirmed_count+1 if association.recognition_source=='field_verified' else 1
        association.recognition_source='field_verified';association.last_confirmed_at=datetime.now(timezone.utc)
    else:
        association=PartMachineAssociation(organization_id=actor.organization_id,part_id=part.id,machine_model=MODEL,recognition_source='field_verified')
        db.add(association)
    db.flush()
    # The audit trail records the actor who explicitly confirmed this field relation.
    db.add(AuditLog(organization_id=actor.organization_id,user_id=actor.user_id,action='verify_viper3_part',entity_type='part_machine_association',entity_id=association.id,metadata_json=json.dumps({'part_id':part.id,'machine_model':MODEL})))
    db.commit()
    return {'association_id':association.id,'part_id':part.id,'machine_model':MODEL,'source':'field_verified','confirmed_count':association.confirmed_count}


@catalog_router.get('/models/viper-3/parts/{part_id}/usage')
def viper3_part_usage(part_id: int,skip: int = Query(0,ge=0),limit: int = Query(25,ge=1,le=100),db: Session = Depends(get_db),actor: Actor = Depends(get_current_actor)):
    from app.services.model_chain import work_order_usage,usage_summary
    part=db.scalar(select(Part).where(Part.id==part_id,Part.organization_id==actor.organization_id))
    if not part:raise HTTPException(404,'Organization part not found')
    records=work_order_usage(db,actor.organization_id).get(part.id,[])
    summary=usage_summary(records);summary.pop('records');summary.pop('records_limit')
    return {'model_id':'viper-3','organization_id':actor.organization_id,'part_id':part.id,'total':len(records),'skip':skip,'limit':limit,'summary':summary,'items':records[skip:skip+limit],'compatibility_note':'Work-order materials report use; they never create field verification or official compatibility.'}


@catalog_router.get('/freestyle/models')
def freestyle_models(actor: Actor = Depends(get_current_actor)):
    from app.services.freestyle_chain import graph
    return {'items':[{'model_id':m['model_id'],'official_model':m['official_model'],'official_part_count':m['official_part_count'],'section_count':len(m['sections'])} for m in graph()['models'].values()],'policy':graph()['policy']}


@catalog_router.get('/freestyle/models/{model_id}')
def freestyle_model(model_id: str,actor: Actor = Depends(get_current_actor)):
    from app.services.freestyle_chain import graph
    model=graph()['models'].get(model_id)
    if not model:raise HTTPException(404,'Freestyle model not found')
    return {**model,'policy':graph()['policy']}


@catalog_router.get('/freestyle/models/{model_id}/parts')
def freestyle_parts(model_id: str,section_id: str | None = None,q: str = Query('',max_length=200),skip: int = Query(0,ge=0),limit: int = Query(25,ge=1,le=100),db: Session = Depends(get_db),actor: Actor = Depends(get_current_actor)):
    from app.services.freestyle_chain import graph,parts
    model=graph()['models'].get(model_id)
    if not model:raise HTTPException(404,'Freestyle model not found')
    if section_id is not None and not any(s['id']==section_id for s in model['sections']):raise HTTPException(404,'Section does not belong to this Freestyle model')
    return parts(db,actor.organization_id,model_id,section_id,q,skip,limit)


@catalog_router.get('/freestyle/models/{model_id}/parts/{part_id}/usage')
def freestyle_part_usage(model_id: str,part_id: int,skip: int = Query(0,ge=0),limit: int = Query(25,ge=1,le=100),db: Session = Depends(get_db),actor: Actor = Depends(get_current_actor)):
    from app.services.freestyle_chain import graph,model_usage
    from app.services.model_chain import usage_summary
    if model_id not in graph()['models']:raise HTTPException(404,'Freestyle model not found')
    part=db.scalar(select(Part).where(Part.id==part_id,Part.organization_id==actor.organization_id))
    if not part:raise HTTPException(404,'Organization part not found')
    records=model_usage(db,actor.organization_id,model_id).get(part.id,[])
    summary=usage_summary(records);summary.pop('records');summary.pop('records_limit')
    return {'model_id':model_id,'part_id':part.id,'organization_id':actor.organization_id,'total':len(records),'skip':skip,'limit':limit,'summary':summary,'items':records[skip:skip+limit],'cross_model_compatibility_confirmed':False}


@catalog_router.post('/freestyle/models/{model_id}/field-verifications')
def freestyle_field_verification(model_id: str,payload: Viper3FieldVerification,db: Session = Depends(get_db),actor: Actor = Depends(get_current_actor)):
    from datetime import datetime,timezone
    from app.models import PartMachineAssociation,AuditLog
    from app.services.freestyle_chain import graph
    require_roles(actor,UserRole.ADMIN,UserRole.MANAGER,UserRole.ENGINEER)
    model=graph()['models'].get(model_id)
    if not model:raise HTTPException(404,'Freestyle model not found')
    part=db.scalar(select(Part).where(Part.id==payload.part_id,Part.organization_id==actor.organization_id))
    if not part:raise HTTPException(404,'Organization part not found')
    name=model['official_model']
    association=db.scalar(select(PartMachineAssociation).where(PartMachineAssociation.organization_id==actor.organization_id,PartMachineAssociation.part_id==part.id,PartMachineAssociation.machine_model==name))
    if association:
        association.confirmed_count=association.confirmed_count+1 if association.recognition_source=='field_verified' else 1
        association.recognition_source='field_verified';association.last_confirmed_at=datetime.now(timezone.utc)
    else:
        association=PartMachineAssociation(organization_id=actor.organization_id,part_id=part.id,machine_model=name,recognition_source='field_verified');db.add(association)
    try:
        db.flush()
        db.add(AuditLog(organization_id=actor.organization_id,user_id=actor.user_id,action='verify_freestyle_part',entity_type='part_machine_association',entity_id=association.id,metadata_json=json.dumps({'part_id':part.id,'machine_model':name})))
        db.commit()
    except IntegrityError:
        db.rollback();raise HTTPException(409,'Concurrent verification; retry request')
    return {'association_id':association.id,'part_id':part.id,'machine_model':name,'source':'field_verified','confirmed_count':association.confirmed_count,'cross_model_compatibility_confirmed':False}


@catalog_router.get('/quest/models')
def quest_models(actor: Actor = Depends(get_current_actor)):
    from app.services.quest_chain import graph
    return {'items':[{'model_id':m['model_id'],'official_model':m['official_model'],'official_part_count':m['official_part_count'],'section_count':len(m['sections'])} for m in graph()['models'].values()],'policy':graph()['policy']}


@catalog_router.get('/quest/models/{model_id}')
def quest_model(model_id: str,actor: Actor = Depends(get_current_actor)):
    from app.services.quest_chain import graph
    model=graph()['models'].get(model_id)
    if not model:raise HTTPException(404,'Quest model not found')
    return {**model,'policy':graph()['policy']}


@catalog_router.get('/quest/models/{model_id}/parts')
def quest_parts(model_id: str,section_id: str | None = None,q: str = Query('',max_length=200),skip: int = Query(0,ge=0),limit: int = Query(25,ge=1,le=100),db: Session = Depends(get_db),actor: Actor = Depends(get_current_actor)):
    from app.services.quest_chain import graph,parts
    model=graph()['models'].get(model_id)
    if not model:raise HTTPException(404,'Quest model not found')
    if section_id is not None and not any(s['id']==section_id for s in model['sections']):raise HTTPException(404,'Section does not belong to this Quest model')
    return parts(db,actor.organization_id,model_id,section_id,q,skip,limit)


@catalog_router.get('/abs/models')
def abs_models(actor: Actor = Depends(get_current_actor)):
    from app.services.abs_chain import graph
    return {'items':[{'model_id':m['model_id'],'official_model':m['official_model'],'official_part_count':m['official_part_count'],'section_count':len(m['sections'])} for m in graph()['models'].values()],'policy':graph()['policy']}


@catalog_router.get('/abs/models/{model_id}')
def abs_model(model_id: str,actor: Actor = Depends(get_current_actor)):
    from app.services.abs_chain import graph
    model=graph()['models'].get(model_id)
    if not model:raise HTTPException(404,'ABS model not found')
    return {**model,'policy':graph()['policy']}


@catalog_router.get('/abs/models/{model_id}/parts')
def abs_parts(model_id: str,section_id: str | None = None,q: str = Query('',max_length=200),skip: int = Query(0,ge=0),limit: int = Query(25,ge=1,le=100),db: Session = Depends(get_db),actor: Actor = Depends(get_current_actor)):
    from app.services.abs_chain import graph,parts
    model=graph()['models'].get(model_id)
    if not model:raise HTTPException(404,'ABS model not found')
    if section_id is not None and not any(s['id']==section_id for s in model['sections']):raise HTTPException(404,'Section does not belong to this ABS model')
    return parts(db,actor.organization_id,model_id,section_id,q,skip,limit)


@catalog_router.get('/ed/models')
def ed_models(actor: Actor = Depends(get_current_actor)):
    from app.services.ed_chain import graph
    return {'items':[{'model_id':m['model_id'],'official_model':m['official_model'],'official_part_count':m['official_part_count'],'section_count':len(m['sections'])} for m in graph()['models'].values()],'policy':graph()['policy']}


@catalog_router.get('/ed/models/{model_id}')
def ed_model(model_id: str,actor: Actor = Depends(get_current_actor)):
    from app.services.ed_chain import graph
    model=graph()['models'].get(model_id)
    if not model:raise HTTPException(404,'ED model not found')
    return {**model,'policy':graph()['policy']}


@catalog_router.get('/ed/models/{model_id}/parts')
def ed_parts(model_id: str,section_id: str | None = None,q: str = Query('',max_length=200),skip: int = Query(0,ge=0),limit: int = Query(25,ge=1,le=100),db: Session = Depends(get_db),actor: Actor = Depends(get_current_actor)):
    from app.services.ed_chain import graph,parts
    model=graph()['models'].get(model_id)
    if not model:raise HTTPException(404,'ED model not found')
    if section_id is not None and not any(s['id']==section_id for s in model['sections']):raise HTTPException(404,'Section does not belong to this ED model')
    return parts(db,actor.organization_id,model_id,section_id,q,skip,limit)


@catalog_router.get('/md/models')
def md_models(actor: Actor = Depends(get_current_actor)):
    from app.services.md_chain import graph
    return {'items':[{'model_id':m['model_id'],'official_model':m['official_model'],'official_part_count':m['official_part_count'],'section_count':len(m['sections'])} for m in graph()['models'].values()],'policy':graph()['policy']}


@catalog_router.get('/md/models/{model_id}')
def md_model(model_id: str,actor: Actor = Depends(get_current_actor)):
    from app.services.md_chain import graph
    model=graph()['models'].get(model_id)
    if not model:raise HTTPException(404,'MD model not found')
    return {**model,'policy':graph()['policy']}


@catalog_router.get('/md/models/{model_id}/parts')
def md_parts(model_id: str,section_id: str | None = None,q: str = Query('',max_length=200),skip: int = Query(0,ge=0),limit: int = Query(25,ge=1,le=100),db: Session = Depends(get_db),actor: Actor = Depends(get_current_actor)):
    from app.services.md_chain import graph,parts
    model=graph()['models'].get(model_id)
    if not model:raise HTTPException(404,'MD model not found')
    if section_id is not None and not any(s['id']==section_id for s in model['sections']):raise HTTPException(404,'Section does not belong to this MD model')
    return parts(db,actor.organization_id,model_id,section_id,q,skip,limit)


@catalog_router.get('/df/models')
def df_models(actor: Actor = Depends(get_current_actor)):
    from app.services.df_chain import graph
    return {'items':[{'model_id':m['model_id'],'official_model':m['official_model'],'official_part_count':m['official_part_count'],'section_count':len(m['sections'])} for m in graph()['models'].values()],'policy':graph()['policy']}


@catalog_router.get('/df/models/{model_id}')
def df_model(model_id: str,actor: Actor = Depends(get_current_actor)):
    from app.services.df_chain import graph
    model=graph()['models'].get(model_id)
    if not model:raise HTTPException(404,'DF model not found')
    return {**model,'policy':graph()['policy']}


@catalog_router.get('/df/models/{model_id}/parts')
def df_parts(model_id: str,section_id: str | None = None,q: str = Query('',max_length=200),skip: int = Query(0,ge=0),limit: int = Query(25,ge=1,le=100),db: Session = Depends(get_db),actor: Actor = Depends(get_current_actor)):
    from app.services.df_chain import graph,parts
    model=graph()['models'].get(model_id)
    if not model:raise HTTPException(404,'DF model not found')
    if section_id is not None and not any(s['id']==section_id for s in model['sections']):raise HTTPException(404,'Section does not belong to this DF model')
    return parts(db,actor.organization_id,model_id,section_id,q,skip,limit)


@catalog_router.get('/db/models')
def db_models(actor: Actor = Depends(get_current_actor)):
    from app.services.db_chain import graph
    return {'items':[{'model_id':m['model_id'],'official_model':m['official_model'],'official_part_count':m['official_part_count'],'section_count':len(m['sections'])} for m in graph()['models'].values()],'policy':graph()['policy']}


@catalog_router.get('/db/models/{model_id}')
def db_model(model_id: str,actor: Actor = Depends(get_current_actor)):
    from app.services.db_chain import graph
    model=graph()['models'].get(model_id)
    if not model:raise HTTPException(404,'DB model not found')
    return {**model,'policy':graph()['policy']}


@catalog_router.get('/db/models/{model_id}/parts')
def db_parts(model_id: str,section_id: str | None = None,q: str = Query('',max_length=200),skip: int = Query(0,ge=0),limit: int = Query(25,ge=1,le=100),db: Session = Depends(get_db),actor: Actor = Depends(get_current_actor)):
    from app.services.db_chain import graph,parts
    model=graph()['models'].get(model_id)
    if not model:raise HTTPException(404,'DB model not found')
    if section_id is not None and not any(s['id']==section_id for s in model['sections']):raise HTTPException(404,'Section does not belong to this DB model')
    return parts(db,actor.organization_id,model_id,section_id,q,skip,limit)


@catalog_router.get('/icecombo/models')
def icecombo_models(actor: Actor = Depends(get_current_actor)):
    from app.services.icecombo_chain import graph
    return {'items':[{'model_id':m['model_id'],'official_model':m['official_model'],'official_part_count':m['official_part_count'],'section_count':len(m['sections'])} for m in graph()['models'].values()],'policy':graph()['policy']}


@catalog_router.get('/icecombo/models/{model_id}')
def icecombo_model(model_id: str,actor: Actor = Depends(get_current_actor)):
    from app.services.icecombo_chain import graph
    model=graph()['models'].get(model_id)
    if not model:raise HTTPException(404,'Ice Combo model not found')
    return {**model,'policy':graph()['policy']}


@catalog_router.get('/icecombo/models/{model_id}/parts')
def icecombo_parts(model_id: str,section_id: str | None = None,q: str = Query('',max_length=200),skip: int = Query(0,ge=0),limit: int = Query(25,ge=1,le=100),db: Session = Depends(get_db),actor: Actor = Depends(get_current_actor)):
    from app.services.icecombo_chain import graph,parts
    model=graph()['models'].get(model_id)
    if not model:raise HTTPException(404,'Ice Combo model not found')
    if section_id is not None and not any(s['id']==section_id for s in model['sections']):raise HTTPException(404,'Section does not belong to this Ice Combo model')
    return parts(db,actor.organization_id,model_id,section_id,q,skip,limit)


@catalog_router.get('/crewserve/models')
def crewserve_models(actor: Actor = Depends(get_current_actor)):
    from app.services.crewserve_chain import graph
    return {'items':[{'model_id':m['model_id'],'official_model':m['official_model'],'official_part_count':m['official_part_count'],'section_count':len(m['sections'])} for m in graph()['models'].values()],'policy':graph()['policy']}


@catalog_router.get('/crewserve/models/{model_id}')
def crewserve_model(model_id: str,actor: Actor = Depends(get_current_actor)):
    from app.services.crewserve_chain import graph
    model=graph()['models'].get(model_id)
    if not model:raise HTTPException(404,'Crew-Serve model not found')
    return {**model,'policy':graph()['policy']}


@catalog_router.get('/crewserve/models/{model_id}/parts')
def crewserve_parts(model_id: str,section_id: str | None = None,q: str = Query('',max_length=200),skip: int = Query(0,ge=0),limit: int = Query(25,ge=1,le=100),db: Session = Depends(get_db),actor: Actor = Depends(get_current_actor)):
    from app.services.crewserve_chain import graph,parts
    model=graph()['models'].get(model_id)
    if not model:raise HTTPException(404,'Crew-Serve model not found')
    if section_id is not None and not any(s['id']==section_id for s in model['sections']):raise HTTPException(404,'Section does not belong to this Crew-Serve model')
    return parts(db,actor.organization_id,model_id,section_id,q,skip,limit)


@catalog_router.get('/selfserve/models')
def selfserve_models(actor: Actor = Depends(get_current_actor)):
    from app.services.selfserve_chain import graph
    return {'items':[{'model_id':m['model_id'],'official_model':m['official_model'],'official_part_count':m['official_part_count'],'section_count':len(m['sections'])} for m in graph()['models'].values()],'policy':graph()['policy']}


@catalog_router.get('/selfserve/models/{model_id}')
def selfserve_model(model_id: str,actor: Actor = Depends(get_current_actor)):
    from app.services.selfserve_chain import graph
    model=graph()['models'].get(model_id)
    if not model:raise HTTPException(404,'Self-Serve model not found')
    return {**model,'policy':graph()['policy']}


@catalog_router.get('/selfserve/models/{model_id}/parts')
def selfserve_parts(model_id: str,section_id: str | None = None,q: str = Query('',max_length=200),skip: int = Query(0,ge=0),limit: int = Query(25,ge=1,le=100),db: Session = Depends(get_db),actor: Actor = Depends(get_current_actor)):
    from app.services.selfserve_chain import graph,parts
    model=graph()['models'].get(model_id)
    if not model:raise HTTPException(404,'Self-Serve model not found')
    if section_id is not None and not any(s['id']==section_id for s in model['sections']):raise HTTPException(404,'Section does not belong to this Self-Serve model')
    return parts(db,actor.organization_id,model_id,section_id,q,skip,limit)


@catalog_router.get('/tj/models')
def tj_models(actor: Actor = Depends(get_current_actor)):
    from app.services.tj_chain import graph
    return {'items':[{'model_id':m['model_id'],'official_model':m['official_model'],'official_part_count':m['official_part_count'],'section_count':len(m['sections'])} for m in graph()['models'].values()],'policy':graph()['policy']}


@catalog_router.get('/tj/models/{model_id}')
def tj_model(model_id: str,actor: Actor = Depends(get_current_actor)):
    from app.services.tj_chain import graph
    model=graph()['models'].get(model_id)
    if not model:raise HTTPException(404,'TJ model not found')
    return {**model,'policy':graph()['policy']}


@catalog_router.get('/tj/models/{model_id}/parts')
def tj_parts(model_id: str,section_id: str | None = None,q: str = Query('',max_length=200),skip: int = Query(0,ge=0),limit: int = Query(25,ge=1,le=100),db: Session = Depends(get_db),actor: Actor = Depends(get_current_actor)):
    from app.services.tj_chain import graph,parts
    model=graph()['models'].get(model_id)
    if not model:raise HTTPException(404,'TJ model not found')
    if section_id is not None and not any(s['id']==section_id for s in model['sections']):raise HTTPException(404,'Section does not belong to this TJ model')
    return parts(db,actor.organization_id,model_id,section_id,q,skip,limit)


@catalog_router.get('/wbk/models')
def wbk_models(actor: Actor = Depends(get_current_actor)):
    from app.services.wbk_chain import graph
    return {'items':[{'model_id':m['model_id'],'official_model':m['official_model'],'official_part_count':m['official_part_count'],'section_count':len(m['sections'])} for m in graph()['models'].values()],'policy':graph()['policy']}


@catalog_router.get('/wbk/models/{model_id}')
def wbk_model(model_id: str,actor: Actor = Depends(get_current_actor)):
    from app.services.wbk_chain import graph
    model=graph()['models'].get(model_id)
    if not model:raise HTTPException(404,'WBK model not found')
    return {**model,'policy':graph()['policy']}


@catalog_router.get('/wbk/models/{model_id}/parts')
def wbk_parts(model_id: str,section_id: str | None = None,q: str = Query('',max_length=200),skip: int = Query(0,ge=0),limit: int = Query(25,ge=1,le=100),db: Session = Depends(get_db),actor: Actor = Depends(get_current_actor)):
    from app.services.wbk_chain import graph,parts
    model=graph()['models'].get(model_id)
    if not model:raise HTTPException(404,'WBK model not found')
    if section_id is not None and not any(s['id']==section_id for s in model['sections']):raise HTTPException(404,'Section does not belong to this WBK model')
    return parts(db,actor.organization_id,model_id,section_id,q,skip,limit)


@catalog_router.get('/series37/models')
def series37_models(actor: Actor = Depends(get_current_actor)):
    from app.services.series37_chain import graph
    return {'items':[{'model_id':m['model_id'],'official_model':m['official_model'],'official_part_count':m['official_part_count'],'section_count':len(m['sections'])} for m in graph()['models'].values()],'policy':graph()['policy']}


@catalog_router.get('/series37/models/{model_id}')
def series37_model(model_id: str,actor: Actor = Depends(get_current_actor)):
    from app.services.series37_chain import graph
    model=graph()['models'].get(model_id)
    if not model:raise HTTPException(404,'37T/F/K model not found')
    return {**model,'policy':graph()['policy']}


@catalog_router.get('/series37/models/{model_id}/parts')
def series37_parts(model_id: str,section_id: str | None = None,q: str = Query('',max_length=200),skip: int = Query(0,ge=0),limit: int = Query(25,ge=1,le=100),db: Session = Depends(get_db),actor: Actor = Depends(get_current_actor)):
    from app.services.series37_chain import graph,parts
    model=graph()['models'].get(model_id)
    if not model:raise HTTPException(404,'37T/F/K model not found')
    if section_id is not None and not any(s['id']==section_id for s in model['sections']):raise HTTPException(404,'Section does not belong to this 37T/F/K model')
    return parts(db,actor.organization_id,model_id,section_id,q,skip,limit)
