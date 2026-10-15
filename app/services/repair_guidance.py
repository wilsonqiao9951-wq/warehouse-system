"""Reviewed case retrieval: learns from explicit outcomes, never auto-confirms fitment."""
from sqlalchemy import select
from app.models import Equipment,RepairCaseReport,Part
from app.services.freestyle_chain import graph,matches_model
from app.services.model_chain import is_viper3,inventory


def machine_model(db,org,work_order):
    equipment=db.scalar(select(Equipment).where(Equipment.id==work_order.equipment_id,Equipment.organization_id==org)) if work_order.equipment_id else None
    if work_order.equipment_id and equipment is None:return None
    labels=[s for s in (work_order.machine_type,equipment.model if equipment else None) if s and s.strip()]
    if not labels:return None
    if all(is_viper3(s) for s in labels):return 'Viper 3 Flavor'
    for mid,m in graph()['models'].items():
        if all(matches_model(s,mid) for s in labels):return m['official_model']
    return None


def guidance(db,org,order,codes):
    model=machine_model(db,org,order);codes={s.strip().casefold() for s in codes if s.strip()}
    reports=list(db.scalars(select(RepairCaseReport).where(RepairCaseReport.organization_id==org,RepairCaseReport.machine_model==model,RepairCaseReport.review_status=='approved',RepairCaseReport.work_order_id!=order.id).order_by(RepairCaseReport.created_at.desc(),RepairCaseReport.id.desc()))) if model and codes else []
    reports=[r for r in reports if codes.intersection(r.symptom_codes)]
    # Repeated submissions from one work order must not inflate supporting case counts.
    latest={}
    for report in reports:latest.setdefault(report.work_order_id,report)
    reports=list(latest.values())
    positive=[r for r in reports if r.outcome=='resolved'];negative=[r for r in reports if r.outcome!='resolved']
    cases=[];part_refs={}
    for r in positive[:10]:
        cases.append({'case_id':r.id,'source_work_order_id':r.work_order_id,'symptom_codes':r.symptom_codes,'reported_steps':r.steps,'result_notes':r.result_notes,'reviewed_by':r.reviewed_by,'reviewed_at':r.reviewed_at,'source':'reviewed_resolved_case'})
        for pid in r.part_ids:part_refs.setdefault(pid,[]).append(r.id)
    local=list(db.scalars(select(Part).where(Part.organization_id==org,Part.id.in_(part_refs)))) if part_refs else [];stock=inventory(db,org,[p.id for p in local])
    return {'engine':'reviewed_case_retrieval','model_training_performed':False,'machine_model':model,'symptom_codes':sorted(codes),'reviewed_resolved_case_count':len(positive),'reviewed_non_resolved_case_count':len(negative),'cases':cases,'part_candidates':[{'part_id':p.id,'part_number':p.part_number,'name':p.name,'source_case_ids':part_refs[p.id],'stock_quantity':sum(r['quantity'] for r in stock.get(p.id,[])),'positions':stock.get(p.id,[]),'compatibility_confirmed':False} for p in local],'non_resolved_cases':[{'case_id':r.id,'reported_steps':r.steps,'outcome':r.outcome,'result_notes':r.result_notes} for r in negative[:10]],'needs_more_evidence':not bool(cases),'policy':'Only same-model, same-organization, manually reviewed cases with matching symptom codes are retrieved. Reported resolution is evidence, not a guaranteed repair or fitment. No automatic work-order completion, inventory use, or cross-model learning.'}


def historical_parts(db,org,order):
    from app.services.model_chain import work_order_usage,is_viper3
    model=machine_model(db,org,order)
    if not model:return []
    if model=='Viper 3 Flavor':matcher=is_viper3
    else:
        mid=next(k for k,v in graph()['models'].items() if v['official_model']==model)
        matcher=lambda value:matches_model(value,mid)
    usages=work_order_usage(db,org,matcher);counts={}
    for pid,records in usages.items():
        evidence=[r for r in records if r['work_order_id']!=order.id and r['is_actual_usage']]
        if evidence:counts[pid]={'source':'reported_work_order_usage','usage_count':len(evidence),'total_quantity':sum(r['quantity'] for r in evidence),'source_work_order_ids':sorted({r['work_order_id'] for r in evidence}),'compatibility_confirmed':False}
    parts=list(db.scalars(select(Part).where(Part.organization_id==org,Part.id.in_(counts)))) if counts else []
    return [{'part_id':p.id,'part_number':p.part_number,'name':p.name,**counts[p.id]} for p in parts]
