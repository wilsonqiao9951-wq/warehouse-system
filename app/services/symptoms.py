"""Versioned observation vocabulary, never diagnosis or compatibility evidence."""
import re
import unicodedata

VERSION = '1.0'
# These are project observation labels, not manufacturer fault-code definitions.
DEFINITIONS = (
    ('no_power', 'power', '无法开机', 'No power', ('不通电', '无法开机', '不开机', 'no power', 'will not power on')),
    ('intermittent_power', 'power', '间歇断电', 'Intermittent power', ('间歇断电', '反复断电', 'intermittent power')),
    ('no_flow', 'dispensing', '不出液', 'No flow', ('不出液', '不出水', '没有出水', 'no flow', 'no dispense')),
    ('low_flow', 'dispensing', '出液流量小', 'Low flow', ('流量小', '出液量小', '出液流量小', '出水量小', 'low flow', 'weak flow')),
    ('leak', 'leak', '漏液', 'Liquid leak', ('漏液', '漏水', '液体泄漏', 'leak', 'liquid leak', 'water leak')),
    ('not_cooling', 'temperature', '不制冷', 'Not cooling', ('不制冷', '温度过高', '饮料不冷', 'not cooling', 'drink warm')),
    ('overcooling', 'temperature', '过度制冷', 'Overcooling', ('过度制冷', '饮料结冰', 'overcooling', 'drink freezing')),
    ('unusual_noise', 'mechanical', '异常噪音', 'Unusual noise', ('异常噪音', '异响', 'unusual noise', 'abnormal noise')),
    ('display_error', 'controls', '显示报错', 'Display error', ('显示报错', '屏幕报错', 'display error', 'error displayed')),
    ('touchscreen_unresponsive', 'controls', '触摸无响应', 'Touchscreen unresponsive', ('触摸无响应', '触屏无响应', 'touchscreen unresponsive')),
    ('no_carbonation', 'beverage_quality', '无气', 'No carbonation', ('无气', '没有碳酸气', 'no carbonation', 'flat drink')),
    ('poor_mix', 'beverage_quality', '饮料混合异常', 'Poor beverage mix', ('饮料混合异常', '味道异常', 'poor mix', 'incorrect beverage mix')),
    ('no_ice', 'ice', '不出冰', 'No ice dispensing', ('不出冰', 'no ice', 'no ice dispensing')),
)


def normalize(value):
    value = unicodedata.normalize('NFKC', value).strip().casefold()
    return re.sub(r'[\s_-]+', ' ', value).strip(' .。!！')


LOOKUP = {}
for code, category, zh, en, aliases in DEFINITIONS:
    for value in (code, zh, en, *aliases):
        key = normalize(value)
        if key in LOOKUP and LOOKUP[key] != code:
            raise RuntimeError('Ambiguous symptom vocabulary')
        LOOKUP[key] = code


def taxonomy():
    return {'version': VERSION, 'source': 'project_observation_taxonomy',
            'items': [{'code': code, 'category': category, 'label_zh': zh, 'label_en': en,
                       'aliases': list(aliases)} for code, category, zh, en, aliases in DEFINITIONS],
            'policy': 'Observation labels only; no diagnosis, model fitment or manufacturer fault-code interpretation.'}


def resolve(codes=(), text='', source='explicit_request', work_order_id=None):
    canonical, unknown, matches = set(), [], []
    for value in codes:
        if not value.strip():
            continue
        code = LOOKUP.get(normalize(value))
        if code:
            canonical.add(code)
            matches.append({'input': value, 'code': code, 'method': 'exact_code_or_alias'})
        elif value not in unknown:
            unknown.append(value)
    # Only whole observation phrases are accepted. Embedded phrases are suggestions,
    # because a longer sentence can negate, question or quote a symptom.
    fragments = [s.strip() for s in re.split(r'[,，;；\n]+', text) if s.strip()]
    unresolved = []
    for fragment in fragments:
        code = LOOKUP.get(normalize(fragment))
        if code:
            canonical.add(code)
            matches.append({'input': fragment, 'code': code, 'method': 'exact_observation_phrase'})
        else:
            unresolved.append(fragment)
    suggestions = set()
    for fragment in unresolved:
        value = normalize(fragment)
        for alias, code in LOOKUP.items():
            if len(alias) < 2:
                continue
            if re.search(r'(?<![a-z0-9])' + re.escape(alias) + r'(?![a-z0-9])', value):
                suggestions.add(code)
    return {'taxonomy_version': VERSION, 'canonical_codes': sorted(canonical),
            'raw_codes': list(codes), 'raw_text': text, 'matches': matches,
            'unknown_codes': unknown, 'unresolved_text': unresolved,
            'suggested_codes': sorted(suggestions - canonical),
            'needs_confirmation': bool(unknown or unresolved or not canonical),
            'source': source, 'work_order_id': work_order_id,
            'matching_policy': 'Only canonical_codes are used; suggestions and unknown inputs never broaden case retrieval.',
            'message': '请确认未分类内容；候选症状不是诊断，不会自动用于检索。' if unknown or unresolved or not canonical else '已按明确症状代码或完整同义说法匹配；不代表故障原因或适配。'}


def report_resolution(report):
    if report.symptom_context:
        return report.symptom_context
    return resolve(report.symptom_codes, source='legacy_report_code_lookup', work_order_id=report.work_order_id)


def report_codes(report):
    return set(resolve(report.symptom_codes)['canonical_codes'])
