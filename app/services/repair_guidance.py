"""Reviewed case retrieval: learns from explicit outcomes, never auto-confirms fitment."""
from sqlalchemy import select
from app.models import Equipment,RepairCaseReport,Part,WorkOrder,Warehouse,StorageLocation
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


CASE_LIMIT = 10
MIN_SUPPORTING_CASES = 2


def _case_source(report):
    return {'case_id': report.id, 'source_work_order_id': report.work_order_id,
            'source_path': f'/api/muse/reports/{report.id}',
            'work_order_context_path': f'/api/work-orders/{report.work_order_id}/service-context',
            'machine_model': report.machine_model, 'symptom_codes': report.symptom_codes,
            'reported_steps': report.steps, 'result_notes': report.result_notes,
            'reviewed_by': report.reviewed_by, 'reviewed_at': report.reviewed_at,
            'outcome': report.outcome, 'source': 'reviewed_resolved_case' if report.outcome == 'resolved' else 'reviewed_non_resolved_case'}


def _stock_context(part, positions, warehouse_ids, active_locations):
    eligible = [p for p in positions if p['warehouse_id'] in warehouse_ids
                and (p['location_id'] is None or p['location_id'] in active_locations)]
    inconsistent = any(p['quantity'] < 0 for p in positions)
    available = sum(p['quantity'] for p in eligible) if part.is_active and not inconsistent else 0
    state = ('inactive_part' if not part.is_active else 'inventory_inconsistent' if inconsistent
             else 'in_stock' if available > 0 else 'out_of_stock')
    notes = {'inactive_part': '此零件已停用，不能作为当前选用建议。',
             'inventory_inconsistent': '库存位置存在负数，需要先核对账实，暂不承诺可用数量。',
             'in_stock': '查询时本组织启用仓库及库位有账面库存；尚未预留，领用前需复核。',
             'out_of_stock': '查询时没有可用位置库存；不自动生成采购、调拨或替代件。'}
    return {'stock_quantity': sum(p['quantity'] for p in positions), 'positions': positions,
            'available_quantity': available, 'available_positions': [p for p in eligible if p['quantity'] > 0] if available else [],
            'availability': state, 'availability_note': notes[state], 'inventory_checked_at_query_time': True,
            'inventory_reserved': False}


def guidance(db, org, order, codes):
    model = machine_model(db, org, order)
    codes = {s.strip().casefold() for s in codes if s.strip()}
    reports = list(db.scalars(select(RepairCaseReport).where(
        RepairCaseReport.organization_id == org, RepairCaseReport.machine_model == model,
        RepairCaseReport.review_status == 'approved', RepairCaseReport.work_order_id != order.id
    ).order_by(RepairCaseReport.created_at.desc(), RepairCaseReport.id.desc()))) if model and codes else []
    source_orders = {o.id: o for o in db.scalars(select(WorkOrder).where(
        WorkOrder.organization_id == org, WorkOrder.id.in_({r.work_order_id for r in reports}))) } if reports else {}
    # Recheck current source identity: a report snapshot must not outlive a corrected model.
    valid_orders = {wid for wid, source in source_orders.items() if machine_model(db, org, source) == model}
    reports = [r for r in reports if r.work_order_id in valid_orders and codes.intersection(r.symptom_codes)]
    latest = {}
    for report in reports:
        latest.setdefault(report.work_order_id, report)
    reports = list(latest.values())
    positive = [r for r in reports if r.outcome == 'resolved']
    negative = [r for r in reports if r.outcome != 'resolved']
    cases = [_case_source(r) for r in positive[:CASE_LIMIT]]
    failed_cases = [_case_source(r) for r in negative[:CASE_LIMIT]]
    notices = []
    def notice(code, message):
        notices.append({'code': code, 'message': message})
    if not model:
        notice('machine_model_unconfirmed', '机型缺失、不支持或与设备记录冲突；请先确认准确机型。')
    if not codes:
        notice('symptom_code_required', '尚未提供症状代码；请补充实际症状和检查结果。')
    if model and codes and not reports:
        notice('no_reviewed_matching_cases', '没有本组织、同一明确机型、同症状的已审核案例，暂不提供维修步骤或零件推荐。')
    elif reports and not positive:
        notice('no_reviewed_resolved_cases', '匹配案例尚无已审核的解决结果；未解决记录仅作为排查背景。')
    if positive and len(positive) < MIN_SUPPORTING_CASES:
        notice('single_supporting_case', '目前仅有一个独立工单的解决案例，证据有限，需要现场核实。')
    if negative:
        notice('non_resolved_evidence_present', '同症状存在未解决或部分解决结果；不能保证历史操作有效。')
    if len(positive) > CASE_LIMIT or len(negative) > CASE_LIMIT:
        notice('case_details_truncated', '案例明细按最近记录限量展示，推荐来源只引用已展示的解决案例。')
    steps = {}
    part_refs = {}
    for r in positive[:CASE_LIMIT]:
        for raw_step in r.steps:
            text = raw_step.strip()
            if not text:
                continue
            key = ' '.join(text.split()).casefold()
            step = steps.setdefault(key, {'text': text, 'source': 'reviewed_case_reported_step',
                'source_case_ids': [], 'source_work_order_ids': [], 'compatibility_confirmed': False,
                'execution_required': False, 'requires_technician_confirmation': True})
            if r.id not in step['source_case_ids']:
                step['source_case_ids'].append(r.id)
                step['source_work_order_ids'].append(r.work_order_id)
        for pid in set(r.part_ids):
            part_refs.setdefault(pid, []).append(r)
    local = list(db.scalars(select(Part).where(Part.organization_id == org, Part.id.in_(part_refs)))) if part_refs else []
    stock = inventory(db, org, [p.id for p in local])
    warehouse_ids = {w.id for w in db.scalars(select(Warehouse).where(
        Warehouse.organization_id == org, Warehouse.is_active.is_(True)))} if local else set()
    active_locations = {l.id for l in db.scalars(select(StorageLocation).where(
        StorageLocation.organization_id == org, StorageLocation.is_active.is_(True)))} if local else set()
    candidates = []
    for part in local:
        refs = part_refs[part.id]
        contrary = [r for r in negative if part.id in r.part_ids]
        availability = _stock_context(part, stock.get(part.id, []), warehouse_ids, active_locations)
        evidence_limited = len(refs) < MIN_SUPPORTING_CASES or bool(contrary)
        reasons = []
        if len(refs) < MIN_SUPPORTING_CASES:
            reasons.append('single_supporting_case')
        if contrary:
            reasons.append('non_resolved_case_mentions_part')
        if availability['availability'] != 'in_stock':
            reasons.append(availability['availability'])
        candidates.append({'part_id': part.id, 'part_number': part.part_number, 'name': part.name,
            'is_active': part.is_active, 'source': 'reviewed_case_report_part_reference',
            'source_case_ids': [r.id for r in refs], 'source_work_order_ids': [r.work_order_id for r in refs],
            'supporting_case_count': len(refs), 'non_resolved_case_count': len(contrary),
            'non_resolved_source_case_ids': [r.id for r in contrary[:CASE_LIMIT]],
            'non_resolved_evidence': [_case_source(r) for r in contrary[:CASE_LIMIT]],
            'matched_symptom_codes': sorted(codes.intersection({s for r in refs for s in r.symptom_codes})),
            'recommendation_reason': f"本组织 {len(refs)} 个同机型、同症状的已审核解决工单提及此零件；报告提及不等于实际安装或确认适配。",
            'evidence_status': 'limited' if evidence_limited else 'multiple_reviewed_cases',
            'needs_more_evidence': evidence_limited, 'cautions': reasons,
            'requires_technician_confirmation': True, 'compatibility_confirmed': False,
            'automatically_selected': False, **availability})
    # Evidence first; stock availability only breaks ties between equal supporting evidence.
    candidates.sort(key=lambda p: (-p['supporting_case_count'], p['non_resolved_case_count'],
                                   not p['is_active'], -p['available_quantity'], p['part_number']))
    for rank, candidate in enumerate(candidates, 1):
        candidate['rank'] = rank
    suggested_steps = sorted(steps.values(), key=lambda s: (-len(s['source_case_ids']), s['text']))
    for step in suggested_steps:
        step['supporting_case_count'] = len(step['source_case_ids'])
        step['needs_more_evidence'] = len(step['source_case_ids']) < MIN_SUPPORTING_CASES
    needs_more = not model or not codes or len(positive) < MIN_SUPPORTING_CASES or bool(negative)
    return {'engine': 'reviewed_case_retrieval', 'model_training_performed': False,
        'machine_model': model, 'symptom_codes': sorted(codes),
        'evidence_scope': {'organization_id': org, 'exact_model_required': True,
                           'matching_symptom_required': True, 'review_status': 'approved'},
        'reviewed_resolved_case_count': len(positive), 'reviewed_non_resolved_case_count': len(negative),
        'cases': cases, 'case_detail_limit': CASE_LIMIT, 'non_resolved_cases': failed_cases,
        'suggested_checks': suggested_steps, 'part_candidates': candidates,
        'needs_more_evidence': bool(needs_more),
        'evidence_status': 'insufficient' if not positive else 'limited' if needs_more else 'multiple_reviewed_cases',
        'evidence_notices': notices, 'minimum_independent_cases_for_multiple_evidence': MIN_SUPPORTING_CASES,
        'part_recommendation_notice': None if candidates else '没有可由已审核解决案例支持的本组织零件候选；不以有库存或历史用料代替维修证据。',
        'ranking_policy': 'Distinct reviewed resolved work orders first; contrary case mentions second; active part and available stock break ties. No statistical confidence or fitment score.',
        'policy': 'Only same-model, same-organization, manually reviewed cases with matching symptom codes are retrieved. Reported resolution is evidence, not a guaranteed repair or fitment. No automatic work-order completion, inventory use, or cross-model learning.'}


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
    return [{'part_id':p.id,'part_number':p.part_number,'name':p.name,'eligible_as_repair_recommendation':False,**counts[p.id]} for p in parts]
