"""Create only specifications/manifests and thin suite descriptors, never candidates."""
import copy
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]
for language,extension in (('rust','rs'),('py','py')):
    for utility in ('cp','mv','mkdir','sort'):
        canonical=json.loads((ROOT/f'experiments/utilities/c-{utility}.json').read_text())
        selector=f'{language}-{utility}'
        name=f'{language}_{utility}'
        manifest=copy.deepcopy(canonical)
        manifest.update(utility=selector,program=name,language={'rust':'Rust','py':'Python'}[language],
                        protocol_version=1,source_path=f'src/{name}/{name}.{extension}',
                        executable_path=f'build/{name}'+('.py' if language=='py' else ''),
                        test_dir=f'tests/{selector}-test-suite',shared_functional_suite=f'tests/c-{utility}-test-suite')
        manifest['judge']=manifest['test_dir']+'/judge_candidate.sh'
        manifest['build_command']=f'python3 "$HELDOUT_ROOT/scripts/docker_benchmark.py" build --utility {selector}'
        manifest['extra_test_command']=f'python3 "$HELDOUT_ROOT/scripts/heldout_judge.py" --utility {selector} --test-dir {manifest["test_dir"]} --candidate {manifest["executable_path"]}'
        directory=ROOT/'prompts/linux-utilities'/selector
        directory.mkdir(parents=True,exist_ok=True)
        for stage in manifest['checkpoints']:
            text=(ROOT/stage['prompt']).read_text()
            text=text.replace(canonical['source_path'],manifest['source_path']).replace(canonical['executable_path'],manifest['executable_path'])
            text=text.replace(canonical['test_dir'],manifest['test_dir']).replace(f'c_{utility}',name)
            c_rules='Use C11 and POSIX.1-2008 library interfaces. Choose the internal architecture and algorithms independently. Do not copy GNU or other implementations, delegate functionality to external utilities, launch subprocesses, or link third-party libraries. Do not add flags or functionality beyond this checkpoint. Handle resource failures without undefined behavior.'
            if language=='rust':
                rules='Use one standalone Rust 2021 source file, Rust 1.85.1 and the standard library only, with applicable POSIX filesystem behavior. Choose the internal architecture and algorithms independently. No unsafe blocks, Cargo dependencies, external utilities, subprocess delegation or copied implementations. Do not add flags or functionality beyond this checkpoint. Handle ordinary errors without panics; preserve arbitrary pathname and file bytes.'
                build=f'rustc --edition=2021 -C opt-level=2 -D warnings {manifest["source_path"]} -o {manifest["executable_path"]}'
            else:
                rules='Use a standalone Python 3.12.8 program with a Python 3 shebang and main entry point, standard library only. Choose the internal architecture and algorithms independently. Do not copy implementations or delegate functionality through external utilities, subprocesses, shells, os.system, popen, exec/spawn or ctypes. Do not add flags or functionality beyond this checkpoint. Preserve arbitrary pathname and file bytes and handle ordinary errors without uncaught tracebacks. The controller verifies nonempty source and compiles it in memory without executing it; execution uses the pinned Python interpreter inside the isolated Linux case container, not a host launcher.'
                build=f'python3 "$HELDOUT_ROOT/scripts/docker_benchmark.py" build --utility {selector}'
                if utility=='sort' and 'semantic anchor' not in text:
                    rules+=' Preserve the established Python semantic anchor `sort_lines`: core sorting/checking behavior must be reachable from main through it. Choose remaining structure freely.'
            assert c_rules in text
            text=text.replace(c_rules,rules)
            text=re.sub(r'    cc -std=c11[^\n]+', '    '+build,text)
            stage['prompt']=str((directory/Path(stage['prompt']).name).relative_to(ROOT))
            target=ROOT/stage['prompt']; assert not target.exists()
            target.write_text(text)
        target=ROOT/f'experiments/utilities/{selector}.json'; assert not target.exists()
        target.write_text(json.dumps(manifest,indent=2)+'\n')
        suite=ROOT/manifest['test_dir']; suite.mkdir()
        (suite/'config.json').write_text(json.dumps({'required_platform':'Linux','benchmark':'linux-utilities',
             'protocol_version':1,'shared_suite':manifest['shared_functional_suite']},indent=2)+'\n')
        (suite/'judge_candidate.sh').write_text('#!/usr/bin/env bash\nset -euo pipefail\n: "${HELDOUT_ROOT:?controller root required}"\ncandidate="${1:?candidate required}"\nshift\nexec python3 "$HELDOUT_ROOT/scripts/docker_benchmark.py" judge --utility '+selector+' --candidate "$candidate" -- "$@"\n')
        (suite/'README.md').write_text(f'# {selector}: shared Linux functional contract\n\nThis descriptor owns no cases or expectations. The planner/bundler/judge resolve\n`{manifest["shared_functional_suite"]}` as the single canonical corpus.\nCompilation/execution use the mandatory Docker backend. Historical suites are unchanged.\n')
print('Created eight manifests, thirty prompts and eight thin suite descriptors')
