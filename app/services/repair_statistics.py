"""Current reviewed outcomes by exact model and canonical symptom, not success rates."""
from urllib.parse import urlencode
from sqlalchemy import select
from app.models import RepairCaseReport, WorkOrder, Part
from app.services import symptoms
from app.services.repair_guidance import machine_model, _case_source


def groups(db, org, model_filter='', symptom_filter=''):
    classification = symptoms.resolve([symptom_filter] if symptom_filter else [])
    if symptom_filter and not classification['canonical_codes']:
        return [], {'unconfirmed_model_reports': 0, 'unclassified_reports': 0}, classification
    codes_filter = set(classification['canonical_codes'])
    rows = db.execute(select(RepairCaseReport, WorkOrder).join(WorkOrder,
        WorkOrder.id == RepairCaseReport.work_order_id).where(
        RepairCaseReport.organization_id == org, WorkOrder.organization_id == org,
        RepairCaseReport.review_status == 'approved').order_by(
        RepairCaseReport.created_at.desc(), RepairCaseReport.id.desc())).all()
    excluded = {'unconfirmed_model_reports': 0, 'unclassified_reports': 0}
    models = {}; seen = set(); grouped = {}
    for report, order in rows:
        if order.id not in models: models[order.id] = machine_model(db, org, order)
        model = models[order.id]
        if not model or model != report.machine_model:
            excluded['unconfirmed_model_reports'] += 1; continue
        codes = symptoms.report_codes(report)
        if not codes:
            excluded['unclassified_reports'] += 1; continue
        if model_filter and model != model_filter: continue
        for code in sorted(codes):
            if codes_filter and code not in codes_filter: continue
            key = (order.id, code)
            if key in seen: continue
            seen.add(key)
            grouped.setdefault((model, code), []).append(report)
    local_parts = {p.id: p for p in db.scalars(select(Part).where(Part.organization_id == org))}
    result = []
    for (model, code), reports in sorted(grouped.items()):
        outcomes = {o: sum(r.outcome == o for r in reports) for o in ['resolved', 'partial', 'unresolved']}
        recurrences = {s: sum((r.repair_followup or {}).get('recurrence', 'unknown') == s for r in reports)
                       for s in ['recurred', 'not_observed', 'unknown']}
        parts = {}; sources = []; incomplete = 0
        for report in reports:
            closure = report.repair_followup or {}
            if not closure.get('actual_parts_complete', False): incomplete += 1
            source = _case_source(report)
            source['reported_at'] = report.created_at
            sources.append(source)
            for used in closure.get('actual_parts', []):
                pid = used['part_id']
                if pid not in local_parts: continue
                part = local_parts[pid]
                entry = parts.setdefault(pid, {'part_id': pid, 'part_number': part.part_number,
                    'name': part.name, 'reported_quantity': 0, 'work_order_count': 0,
                    'source_case_ids': [], 'compatibility_confirmed': False})
                entry['reported_quantity'] += used['quantity']; entry['work_order_count'] += 1
                entry['source_case_ids'].append(report.id)
        cautions = []
        if len(reports) < 2: cautions.append('single_or_no_independent_case')
        if recurrences['unknown']: cautions.append('recurrence_observation_incomplete')
        if incomplete: cautions.append('actual_parts_incomplete')
        if recurrences['recurred'] or outcomes['partial'] or outcomes['unresolved']:
            cautions.append('contrary_outcomes_require_review')
        params = urlencode({'machine_model': model, 'symptom_code': code})
        result.append({'machine_model': model, 'symptom_code': code, 'work_order_count': len(reports),
            'outcome_counts': outcomes, 'recurrence_counts': recurrences,
            'actual_parts_incomplete_case_count': incomplete,
            'actual_parts': sorted(parts.values(), key=lambda p: (-p['work_order_count'], p['part_number'])),
            'repeat_failure_signal': recurrences['recurred'] > 0 or outcomes['unresolved'] + outcomes['partial'] >= 2,
            'needs_more_evidence': bool(cautions), 'evidence_cautions': cautions,
            'source_cases': sources, 'sources_path': '/api/muse/repair-statistics/cases?' + params,
            'guidance_query': {'resource': 'repair_guidance', 'symptom_code': code},
            'guidance_requirement': 'Supply the target work_order_id of this exact model; guidance rechecks model and organization and excludes the target work order.',
            'compatibility_confirmed': False})
    return result, excluded, classification


def summary(db, org, model='', code='', skip=0, limit=25):
    items, excluded, classification = groups(db, org, model, code)
    page = items[skip:skip + limit]
    for item in page:
        item['source_case_count'] = len(item['source_cases'])
        item['source_cases'] = item['source_cases'][:20]
        item['source_cases_truncated'] = item['source_case_count'] > 20
    return {'items': page, 'total': len(items), 'skip': skip, 'limit': limit,
        'organization_id': org, 'excluded_report_counts': excluded,
        'symptom_resolution': classification, 'needs_more_evidence': not items or any(i['needs_more_evidence'] for i in items),
        'notice': 'No confirmed reviewed matching evidence.' if not items else None,
        'policy': 'Latest approved report per work order and canonical symptom, with current exact model validation. Multi-symptom cases appear in each group; do not sum groups as distinct jobs. Quantities are latest reported actual-use snapshots, not inventory movements, cumulative consumption or recommended quantities. Recurrence observations have unequal follow-up periods; counts are not success or recurrence rates. Statistics do not change guidance or fitment.'}
