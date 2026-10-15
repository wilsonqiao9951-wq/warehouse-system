"""Prepare reversible catalog views without changing collected source files."""
import csv
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
from scripts.audit_catalog import ROOT, LIST_FIELDS, identifier, valid_url

OUT = ROOT / 'data' / 'organized'


def prepare():
    OUT.mkdir(parents=True, exist_ok=True)
    summary = {'sources': {}, 'datasets': {}, 'policy': 'source-preserving; no inferred facts; no automatic duplicate deletion'}
    queue = []
    decision_path = ROOT / 'data/verification/decisions.json'
    decisions = json.loads(decision_path.read_text()) if decision_path.exists() else []
    enrichment_path = ROOT / 'data/verification/field_enrichment.json'
    if enrichment_path.exists():
        decisions.extend(json.loads(enrichment_path.read_text()))
    supplemental_path = ROOT / 'data/verification/official_supplement.json'
    if supplemental_path.exists():
        decisions.extend(json.loads(supplemental_path.read_text()))
    reverse_path = ROOT / 'data/verification/reverse_manual_enrichment.json'
    if reverse_path.exists():
        decisions.extend(json.loads(reverse_path.read_text()))
    manual_decision_path = ROOT / 'data/verification/manual_decisions.json'
    manual_decisions = {d['source_index']: d for d in json.loads(manual_decision_path.read_text())} if manual_decision_path.exists() else {}
    by_index = {}
    for decision in decisions:
        by_index.setdefault(decision['source_index'], []).append(decision)
    for kind in ('parts', 'manuals'):
        path = ROOT / f'{kind}_index.json'
        source = path.read_bytes()
        rows = json.loads(source)
        summary['sources'][path.name] = {'sha256': sha256(source).hexdigest(), 'rows': len(rows)}
        organized = []
        stats = Counter()
        for index, raw in enumerate(rows):
            record = dict(raw)
            changes = []
            for field, value in raw.items():
                if isinstance(value, str):
                    record[field] = value.strip() or None
                    if record[field] != value:
                        changes.append(f'{field}:empty_or_whitespace')
                if field in LIST_FIELDS:
                    if value is None or value == '':
                        record[field] = []
                    elif isinstance(value, str) and value.strip():
                        record[field] = [value.strip()]
                    elif isinstance(value, list) and all(isinstance(v, str) for v in value):
                        record[field] = list(dict.fromkeys(v.strip() for v in value if v.strip()))
                    else:
                        queue.append({'dataset': kind, 'source_index': index, 'priority': 'P1', 'reason': f'{field}:unexpected_type'})
                    if record[field] != value:
                        changes.append(f'{field}:array_normalized')
            unavailable = []
            for field in ('page_url', 'image_url', 'manual_pdf_url'):
                if record.get(field) and not valid_url(record[field]):
                    unavailable.append(field)
                    record[field] = None
                    changes.append(f'{field}:unusable_url')
            verification = []
            verified_classification = None
            if kind == 'parts':
                current_hash = sha256(json.dumps(raw,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
                for decision in by_index.get(index, []):
                    if current_hash != decision['source_sha256']:
                        raise ValueError(f'Stale verification decision for source index {index}')
                    record.update(decision['patch'])
                    changes.extend(f'{field}:verified_override' for field in decision['patch'])
                    verification.append({'status': decision['status'], 'reason': decision['reason'], 'evidence': decision.get('evidence'), 'equipment_reference_evidence': decision.get('equipment_reference_evidence', [])})
                    if decision['status'] in {'unresolved', 'quarantined'}:
                        queue.append({'dataset': kind, 'source_index': index, 'priority': 'P1' if decision['status'] == 'quarantined' else 'P2', 'reason': decision['reason']})
                    verified_classification = decision.get('classification', verified_classification)
            if kind == 'manuals' and index in manual_decisions:
                decision = manual_decisions[index]
                if sha256(json.dumps(raw,sort_keys=True,ensure_ascii=False).encode()).hexdigest() != decision['source_sha256']:
                    raise ValueError('Stale manual verification decision')
                record.update(decision['patch'])
                changes.extend(f'{field}:verified_override' for field in decision['patch'])
                verification.append({'status': decision['status'], 'reason': decision['reason'], 'evidence': decision.get('evidence'), 'equipment_reference_evidence': decision.get('equipment_reference_evidence', [])})
            primary = identifier(raw.get('part_number')) if kind == 'parts' else None
            display_name = record.get('title') or record.get('name') or record.get('description') or primary or '未命名资料'
            missing = []
            fields = ('name', 'description', 'status', 'manufacturer', 'fits_equipment_models') if kind == 'parts' else ('title', 'manual_pdf_url', 'equipment_models', 'page_url')
            for field in fields:
                if not record.get(field):
                    missing.append(field)
            if kind == 'parts':
                entry_type = str(record.get('entry_type') or '').casefold()
                stock_candidate = bool(primary and isinstance(record.get('name') or record.get('description'), str) and entry_type not in {'equipment', 'manual', 'test'} and len(primary) <= 120 and len(str(record.get('name') or record.get('description'))) <= 255)
                classification = 'equipment' if entry_type == 'equipment' else 'part_candidate' if stock_candidate else 'needs_classification'
                if not stock_candidate and verified_classification not in {'equipment', 'manual_section'}:
                    queue.append({'dataset': kind, 'source_index': index, 'priority': 'P1', 'reason': 'not_ready_for_part_import'})
                if verified_classification:
                    classification = verified_classification
                    stock_candidate = False
                if record.get('stock_import_candidate') is False:
                    stock_candidate = False
                record['normalized_part_number'] = primary
                record['stock_import_candidate'] = stock_candidate
            else:
                classification = 'manual_with_pdf' if record.get('manual_pdf_url') else 'manual_source_page' if record.get('page_url') else 'manual_reference_only'
                if classification == 'manual_reference_only':
                    queue.append({'dataset': kind, 'source_index': index, 'priority': 'P1', 'reason': 'no_pdf_or_source_page'})
            stats[classification] += 1
            stats['changed_records'] += bool(changes)
            stats['unusable_url_fields'] += len(unavailable)
            record['_organization'] = {'source_index': index, 'source_file': path.name, 'content_id': sha256(json.dumps(raw,sort_keys=True,ensure_ascii=False).encode()).hexdigest(), 'display_name': display_name, 'classification': classification, 'missing_fields': missing, 'unusable_url_fields': unavailable, 'changes': changes, 'verification': verification}
            organized.append(record)
        (OUT / f'{kind}_catalog.json').write_text(json.dumps(organized, ensure_ascii=False, indent=2))
        summary['datasets'][kind] = dict(stats)
        assert path.read_bytes() == source
    with (OUT / 'follow_up.csv').open('w',encoding='utf-8-sig',newline='') as file:
        writer = csv.DictWriter(file,fieldnames=['dataset','source_index','priority','reason']); writer.writeheader(); writer.writerows(queue)
    (OUT / 'manifest.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
    (OUT / 'README.md').write_text('''# 整理数据\n\nparts_catalog.json 与 manuals_catalog.json 是原始索引的可重建视图。原始文件保持不变，后端现已使用整理视图。\n\n规则：空字符串转为 null；已知数组字段的空值转为 []；字符串数组去首尾空白和完全重复项；不可用 URL 转为 null，并记录字段。非空字符串数组字段包装为单元素数组，保留完整原值、不猜测拆分；其他类型异常保留。核验覆写来自 ../verification/decisions.json，应用前逐条校验原始记录哈希。\n\n每条记录的 _organization 提供来源文件、原始数组位置、内容哈希、变更列表、缺失字段与分类。display_name 是展示回退值，不代表补齐原始名称。stock_import_candidate 只代表格式满足基础导入条件，不代表适配或安全性已经确认。原始事实可通过来源索引恢复。\n\n没有删除重复项、推测机型或替代件，也没有创建库存数量。follow_up.csv 是后续补充任务；完整审核问题见 ../reviewed/review_queue.csv。\n\n运行：在项目根目录执行 python -m scripts.prepare_catalog。\n''')
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    return summary


if __name__ == '__main__':
    prepare()
