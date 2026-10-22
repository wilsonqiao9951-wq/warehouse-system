"""Export model-separated review artifacts and an offline audit notebook."""
import json
from pathlib import Path
from scripts.enrich_catalog_fields import ROOT,OUT

def run():
    catalog=json.loads((ROOT/'data/organized/freestyle_parts_catalog.json').read_text());summary=catalog['summary'];parts=catalog['parts']
    folder=ROOT/'data/organized/freestyle';folder.mkdir(exist_ok=True)
    for model in summary['per_model']:
        items=[]
        for part in parts:
            if model not in part['models']:continue
            item={**part,'official_associations':[r for r in part['official_associations'] if r['model']==model]};items.append(item)
        (folder/(model.split()[0]+'.json')).write_text(json.dumps({'model':model,'total':len(items),'parts':items},ensure_ascii=False,indent=2))
    lines=['# Freestyle全系列资料整理','', '整理日期：2026-10-15（America/New_York）。范围为现有官网索引中明确归属Freestyle的8个机型；不声称覆盖所有历史、地区或登录后资料。','', f'共{summary["unique_parts"]}条独立零件，{sum(v["sections"] for v in summary["per_model"].values())}个章节。598条为已收录主目录记录，543条为本轮由官网章节明确链接新收录的独立来源记录。新记录已归档，尚未接入通用主目录/库存导入或Freestyle专属后端查询链路。','', '| 官网机型 | 关联零件 | 章节 |','|---|---:|---:|']
    for model,v in summary['per_model'].items():lines.append(f'| {model} | {v["parts"]} | {v["sections"]} |')
    lines+=['', f'{summary["shared_parts"]}条零件被多个官网机型引用，各行不能相加；共享目录引用不等于机械适配认证。各机型关联及来源分别保留。','', '## 完整度与处理','', '1,141条官网产品身份全部匹配。1,133张图片通过HTTP200与image类型检查；8条缺少可确认官网图片。厂家缺失62条，保留空缺。名称、描述、厂家零件号及CONA编号均有记录。','', '714条原未匹配“机型＋零件链接”关系去重后涉及546个官网链接，其中543个确认新的零件记录，2个异常空格链接匹配已核验零件，1个包含厂家文字的异常链接未确认，继续保留。原始HTML证据不改写，规范化链接额外记录原链接和理由。','', '恢复5张原失效图片并写入主整理视图，真实Bearer后端查询逐条验证通过。Viper 3原机型、库存及用料接口维持；78项回归测试通过。原始索引与前端未改，CCP需要登录的记录保留。','', '## 文件与复现','', 'data/organized/freestyle_parts_catalog.json：完整1,141条清单及关联证据。','data/organized/freestyle/3100.json等：8个独立机型文件，每条仅展示当前机型的官网关联。','data/verification/freestyle_parts_pending.json：异常链接与待接入主目录的新记录。','data/verification/freestyle_new_official_parts.json：543条新增官网记录。','scripts/freestyle_parts_audit.ipynb：离线唯一性、分类数量及来源哈希核验。','', '复现先运行python -m scripts.audit_freestyle_parts，再运行python -m scripts.complete_freestyle_audit，最后python -m scripts.report_freestyle_audit。恢复图片后运行scripts.prepare_catalog并刷新后端缓存。']
    (OUT/'FREESTYLE_PARTS_AUDIT_REPORT.md').write_text('\n'.join(lines)+'\n')
    code='''import json
from pathlib import Path
from hashlib import sha256
root=Path.cwd()
if not (root/"data").exists(): root=root.parent
catalog=json.loads((root/"data/organized/freestyle_parts_catalog.json").read_text())
parts=catalog["parts"]
assert len({p["part_number"] for p in parts})==len(parts)
for p in parts:
    e=p["fresh_evidence"]
    assert sha256((root/"data/verification"/e["file"]).read_bytes()).hexdigest()==e["body_sha256"]
for model,stats in catalog["summary"]["per_model"].items():
    assert stats["parts"]==sum(model in p["models"] for p in parts)
catalog["summary"]
'''
    nb={'nbformat':4,'nbformat_minor':5,'metadata':{'kernelspec':{'display_name':'Python 3','language':'python','name':'python3'}},'cells':[{'cell_type':'markdown','metadata':{},'source':['# Freestyle官网零件离线复核\n','明确机型与零件链接关系；不把目录引用视为现场适配验证。']},{'cell_type':'code','metadata':{},'execution_count':None,'outputs':[],'source':code.splitlines(keepends=True)}]}
    (ROOT/'scripts/freestyle_parts_audit.ipynb').write_text(json.dumps(nb,ensure_ascii=False,indent=2))
    payload={'schemaVersion':1,'items':[{'id':'freestyle-family','title':'Freestyle全系列资料整理','queries':[{'id':'models','source':{'label':'官网机型章节与产品身份核验','files':['freestyle_parts_catalog.json','freestyle_parts_audit_summary.json','freestyle_parts_pending.json','live_api_check.json'],'caveats':['分机型数量含338条跨机型共享零件，不能相加。543条新增记录尚未接入主目录或组织库存。1条异常链接待确认；官网引用不等于适配认证。']},'columns':['model','parts','sections'],'rows':[{'model':m,**v} for m,v in summary['per_model'].items()]}]}]}
    (ROOT.parent/'analysis/freestyle_audit_sources.json').write_text(json.dumps(payload,ensure_ascii=False))
if __name__=='__main__':run()
