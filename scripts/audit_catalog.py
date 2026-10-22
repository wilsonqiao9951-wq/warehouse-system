"""Offline audit and conservative normalization. Never modifies source indexes."""
import csv
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
import re
from urllib.parse import urlsplit, unquote

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'data' / 'reviewed'
LIST_FIELDS = {'fits_equipment_models', 'equipment_models', 'symptom_keywords', 'parents', 'equipment_page_urls', 'legacy_ids'}


def identifier(value):
    return re.sub(r'^CCP[- ]?(\d+)$', r'CCP \1', str(value or '').strip().upper())


def valid_url(value):
    try:
        parsed = urlsplit(value)
        return parsed.scheme in {'http', 'https'} and bool(parsed.netloc) and not parsed.username and not parsed.password
    except (ValueError, TypeError):
        return False


def run():
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = {'mode': 'offline-conservative', 'source_files': {}, 'datasets': {}, 'limitations': [
        'No live source verification or collection resumed.',
        'Local snapshot has 22,897 parts; Muse reports a newer 23,057-row snapshot not available here.',
        'Missing manufacturer/status/model fields are not inferred.',
        'Shared page URLs are flagged, not automatically deduplicated.',
        'Source records are retained; normalized files are not yet used by the application.'
    ]}
    issues = []
    for kind in ('parts', 'manuals'):
        path = ROOT / f'{kind}_index.json'
        raw = path.read_bytes()
        rows = json.loads(raw)
        assert isinstance(rows, list)
        manifest['source_files'][path.name] = {'sha256': sha256(raw).hexdigest(), 'bytes': len(raw), 'rows': len(rows)}
        normalized = []
        keys = defaultdict(list)
        pages = defaultdict(list)
        missing = Counter()
        changes = Counter()
        required = ('part_number', 'name', 'description', 'page_url', 'status', 'manufacturer', 'fits_equipment_models') if kind == 'parts' else ('title', 'manual_pdf_url', 'equipment_models', 'page_url')
        for index, row in enumerate(rows):
            record_id = kind + '-' + sha256(json.dumps(row, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:24]
            flags = []
            if not isinstance(row, dict):
                issues.append({'dataset': kind, 'source_index': index, 'record_id': record_id, 'field': '', 'issue': 'non_object_record', 'value': repr(row), 'severity': 'high'})
                normalized.append({'record_id': record_id, 'source_index': index, 'raw': row, 'review_required': True})
                continue
            data = {}
            for field, value in row.items():
                if isinstance(value, str):
                    cleaned = value.strip()
                    if cleaned != value:
                        changes['trim_whitespace'] += 1
                    data[field] = cleaned
                elif field in LIST_FIELDS and isinstance(value, list) and all(isinstance(item, str) for item in value):
                    cleaned = list(dict.fromkeys(item.strip() for item in value if item.strip()))
                    if cleaned != value:
                        changes['normalize_string_list'] += 1
                    data[field] = cleaned
                else:
                    data[field] = value
            def flag(field, issue, severity='medium'):
                flags.append(issue + ':' + field)
                issues.append({'dataset': kind, 'source_index': index, 'record_id': record_id, 'field': field, 'issue': issue, 'value': json.dumps(row.get(field), ensure_ascii=False), 'severity': severity})
            for field in required:
                if not data.get(field):
                    missing[field] += 1
                    flag(field, 'missing_value', 'high' if field in {'part_number', 'name', 'title'} else 'medium')
            for field in LIST_FIELDS:
                if field in data and data[field] not in (None, '') and not isinstance(data[field], list):
                    flag(field, 'expected_array')
            for field in ('page_url', 'image_url', 'manual_pdf_url'):
                if data.get(field) and not valid_url(data[field]):
                    flag(field, 'invalid_or_unsafe_url', 'high')
            if kind == 'parts':
                number = data.get('part_number')
                if number is not None and not isinstance(number, str):
                    flag('part_number', 'expected_string', 'high')
                key = identifier(number)
                if key:
                    keys[key].append(index)
                data['normalized_part_number'] = key
                page = data.get('page_url')
                if key and isinstance(page, str) and valid_url(page):
                    slug = unquote(urlsplit(page).path).casefold()
                    simple = re.sub(r'[^a-z0-9]', '', key.casefold())
                    if simple and simple not in re.sub(r'[^a-z0-9]', '', slug):
                        flag('page_url', 'number_not_in_source_path', 'high')
            page = data.get('page_url')
            if isinstance(page, str) and page:
                pages[page].append(index)
            data.update(record_id=record_id, source_index=index, source_file=path.name, quality_flags=flags, review_required=bool(flags))
            normalized.append(data)
        for field, groups in [('normalized_part_number', keys), ('page_url', pages)]:
            for value, indices in groups.items():
                if len(indices) > 1:
                    for index in indices:
                        issue = 'duplicate_number' if field == 'normalized_part_number' else 'shared_source_page'
                        normalized[index]['quality_flags'].append(issue + ':' + field)
                        normalized[index]['review_required'] = True
                        issues.append({'dataset': kind, 'source_index': index, 'record_id': normalized[index]['record_id'], 'field': field, 'issue': issue, 'value': value, 'severity': 'high' if field == 'normalized_part_number' else 'medium'})
        (OUT / f'{kind}_normalized.json').write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding='utf-8')
        dataset_issues = [item for item in issues if item['dataset'] == kind]
        manifest['datasets'][kind] = {'rows': len(rows), 'missing': dict(missing), 'safe_changes': dict(changes), 'issue_counts': dict(Counter(item['issue'] for item in dataset_issues)), 'review_rows': sum(bool(row.get('review_required')) for row in normalized), 'duplicate_number_groups': sum(len(v) > 1 for v in keys.values()), 'shared_page_groups': sum(len(v) > 1 for v in pages.values())}
        assert path.read_bytes() == raw, 'Source changed during audit'
    with (OUT / 'review_queue.csv').open('w', encoding='utf-8-sig', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=['dataset', 'source_index', 'record_id', 'field', 'issue', 'severity', 'value'])
        writer.writeheader()
        writer.writerows(issues)
    with (OUT / 'priority_review.csv').open('w', encoding='utf-8-sig', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=['dataset', 'source_index', 'record_id', 'field', 'issue', 'severity', 'value'])
        writer.writeheader()
        writer.writerows(item for item in issues if item['severity'] == 'high')
    (OUT / 'audit_manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = ['# myCoke 现有数据审核', '', '离线审核；原始索引保持不变。标准化副本尚未替换应用的数据源。', '', '| 数据集 | 记录数 | 需核验记录 | 重复编号组 | 共用来源页组 |', '|---|---:|---:|---:|---:|']
    for kind, d in manifest['datasets'].items():
        lines.append(f"| {kind} | {d['rows']} | {d['review_rows']} | {d['duplicate_number_groups']} | {d['shared_page_groups']} |")
    for kind, d in manifest['datasets'].items():
        lines.extend(['', f'## {kind} 空缺字段', '', '| 字段 | 空缺数 | 空缺比例 |', '|---|---:|---:|'])
        for field, count in d['missing'].items():
            lines.append(f"| {field} | {count} | {count / d['rows']:.1%} |")
        lines.extend(['', '检查项：' + json.dumps(d['issue_counts'], ensure_ascii=False), '', '安全整理：' + json.dumps(d['safe_changes'], ensure_ascii=False)])
    lines.extend(['', '## 边界与交接', '', '本地缺少 Muse 最新的一批 160 条及批次台账，不能独立认证扫描水位。', '编号与 URL 路径不一致是核验候选，不直接判定链接错误；CCP 外部链接尤其需要人工确认。', '手册共用来源页面不等于重复文件；不自动删除。', '所有源字段保留，只清理首尾空白及字符串数组中的空值/完全重复值；不填造名称、状态或适用型号。', '记录 ID 由原始内容哈希生成，不依赖数组位置；内容更新后 ID 会变化，不作为永久业务 ID。', 'review_queue.csv 每行是一项问题，同一记录可有多项。空缺包含缺字段、null、空字符串及空数组。', '', '## 下一步', '', '1. 核对编号与来源 URL、空名称和手册标题。', '2. 获取最新快照、批次台账和合并脚本，校验差异后同步。', '3. 优先补充常修设备的适用机型、替代件及手册关联。', '4. 定义稳定实体键和增量更新规则，再切换应用数据源。'])
    (OUT / 'AUDIT_REPORT.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps(manifest['datasets'], ensure_ascii=False, indent=2))
    return manifest


if __name__ == '__main__':
    run()
