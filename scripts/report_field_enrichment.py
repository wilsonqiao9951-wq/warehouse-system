"""Reconcile original versus organized missing fields and preserve audit evidence."""
from collections import Counter
import json
from pathlib import Path
from scripts.audit_catalog import ROOT


def run():
    original=json.loads((ROOT/'parts_index.json').read_text())
    organized=json.loads((ROOT/'data/organized/parts_catalog.json').read_text())
    decisions=json.loads((ROOT/'data/verification/field_enrichment.json').read_text())
    fields=('name','description','fits_equipment_models')
    result={'source_rows':len(original),'checked':len(decisions),'statuses':dict(Counter(d['status'] for d in decisions)), 'enrichment_fields':dict(Counter(k for d in decisions for k in d['patch'])), 'missing_before':{f:sum(not r.get(f) for r in original) for f in fields}, 'missing_after':{f:sum(not r.get(f) for r in organized) for f in fields}}
    pending=[d for d in decisions if d['status']!='confirmed']
    (ROOT/'data/verification/field_enrichment_summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    (ROOT/'data/verification/field_enrichment_unresolved.json').write_text(json.dumps(pending,ensure_ascii=False,indent=2))
    lines=['# 零件缺失字段补全','', '仅按匹配产品ID的官网副标题、长描述和明确手册引用补全；前端与原始索引未修改。', '', '| 字段 | 原始空缺 | 整理后空缺 |', '|---|---:|---:|']
    for f in fields:lines.append(f"| {f} | {result['missing_before'][f]} | {result['missing_after'][f]} |")
    lines.extend(['',f"本轮累计核对 {result['checked']} 条；状态：{result['statuses']}。",'', '补全字段数（与原始文件比，不代表人工确认机械兼容性）：'+json.dumps(result['enrichment_fields'],ensure_ascii=False),'', '## 数据依据与边界','', 'field_enrichment.json 保存每条覆写的来源编号、源记录哈希、网页哈希和设备手册引用；field_pages 保存原始网页证据。', '适用机型来自官网 Parts Manuals Referencing This Part 的引用关系，代表目录关联，不替代现场适配核对。', '官网没有给出信息的记录保留空缺；请求失败或身份不匹配不写入字段。', '自动识别的设备和章节从零件接口分离，原始数据仍保留在整理视图中。', 'CCP需登录记录继续隔离。', '已核对但官网无明确手册引用的条目保留机型空缺；身份或访问未确认记录继续待核验。不能把来源已检查描述为全部字段已补齐。', '', '## 继续执行','', 'python -m scripts.enrich_catalog_fields --limit 240', 'python -m scripts.prepare_catalog', 'python -m scripts.report_field_enrichment', '', '更新后重启后端。脚本使用已保存页面证据，重复运行跳过已核对记录；失败项单独保存以便后续重试。'])
    (ROOT/'data/verification/FIELD_ENRICHMENT_REPORT.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':run()
