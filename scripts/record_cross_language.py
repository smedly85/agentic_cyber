"""Record current cross-language plans/provenance; never execute candidate code."""
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
from docker_benchmark import ROOT, settings, invoke
from linux_utilities_catalog import SELECTORS, suite_root, utility_name, language_name
import lineage_plan
import stage_test_bundle
import check_heldout_isolation
import prompt_render

OUT=ROOT/'docs/benchmarks/cross-language-validation'
config=settings()
versions={language:invoke('toolchain',{'language':language}) for language in ('c','rust','py')}
(OUT/'toolchains.json').write_text(json.dumps({'lock':config,'observed':versions},indent=2)+'\n')
for name,cmd in {
    'docker-version.json':['docker','version','--format','{{json .}}'],
    'docker-info.json':['docker','info','--format','{{json .}}'],
    'rust-image-inspect.json':['docker','image','inspect',config['rust_compiler_image']],
    'oracle-image-inspect.json':['docker','image','inspect',config['oracle_image']],
}.items():
    (OUT/name).write_bytes(subprocess.check_output(cmd,timeout=30))

report={'benchmark':'linux-utilities','protocol_version':1,'platform':config['platform'],'utilities':{}}
for selector in SELECTORS:
    plan=lineage_plan.resolve_plan(ROOT,selector,'','0',None,0,0)
    assert plan['config_fingerprint']==lineage_plan.fingerprint(plan)
    manifest=json.loads((ROOT/f'experiments/utilities/{selector}.json').read_text())
    suite=suite_root(ROOT,selector)
    hidden=json.loads(gzip.decompress((suite/'heldout/heldout_cases.json.gz').read_bytes()))['cases']
    validation=json.loads((OUT/f'rename-oracle/validated/c-{utility_name(selector)}/validation.json').read_text())
    rows=[]
    for checkpoint in plan['checkpoints']:
        bundle=stage_test_bundle.build_payload(ROOT,plan['test_dir'],checkpoint,selector)
        rendered=prompt_render.render_file(ROOT,ROOT/checkpoint['prompt'])
        assert rendered.count(prompt_render.notice_text(ROOT))==1
        oracle=next(row for row in validation['checkpoints'] if row['checkpoint']==checkpoint['id'])
        rows.append({'id':checkpoint['id'],'flags':checkpoint['implemented_flags'],
                     'prompt':checkpoint['prompt'],'public_definitions':bundle['manifest']['cases_included'],
                     'heldout_definitions':sum(set(c.get('flags',[]))<=set(checkpoint['implemented_flags']) for c in hidden),
                     'public_executions':oracle['public']['PASS'],'heldout_executions':oracle['heldout']['PASS'],
                     'bundle_fingerprint':bundle['manifest']['bundle_fingerprint'],
                     'rendered_prompt_sha256':hashlib.sha256(rendered.encode()).hexdigest()})
    leaks,count,values=check_heldout_isolation.scan_utility(ROOT,selector)
    assert not leaks
    report['utilities'][selector]={'manifest':f'experiments/utilities/{selector}.json','language':language_name(selector),
        'suite':plan['test_dir'],'canonical_suite':str(suite.relative_to(ROOT)),
        'source':plan['source_path'],'executable':plan['executable_path'],
        'config_fingerprint':plan['config_fingerprint'],'checkpoints':rows,
        'heldout_isolation':{'checkpoints':count,'identifying_values':values,'leaks':0}}
(ROOT/'docs/benchmarks/linux-utilities-static-report.json').write_text(json.dumps(report,indent=2)+'\n')
(OUT/'final-fingerprints.json').write_text(json.dumps({s:v['config_fingerprint'] for s,v in report['utilities'].items()},indent=2)+'\n')
print('Recorded 12 toolchain-backed plans, 45 rendered prompts/fingerprints and held-out isolation')
