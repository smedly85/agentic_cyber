"""Ordinary native compilation/execution ONLY. No analysis or tracing tools."""
import argparse
import json
import os
import subprocess
from validate_corpus import HERE,ROOT,read,sha,validate,require
from corpus_integrity import verify_instruments,verify_std


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--label',required=True);args=parser.parse_args()
    require(args.label.replace('-','').isalnum(),'Invalid output label')
    frozen=validate();before=verify_instruments();manifest=read(HERE/'fixture_manifest.json')
    output=ROOT/'build/cross-language-calibration-corpus-smoke'/args.label
    output.mkdir(parents=True,exist_ok=False)
    records=[]
    for pair in manifest['pairs']:
        for language,prefix in [('C','c'),('Rust','rust')]:
            config=pair['build_configuration'][language]
            compiler=config['compiler'].replace('$REPO',str(ROOT))
            # Only the pinned ordinary compiler is allowed as the executable.
            expected='/usr/lib/llvm-21/bin/clang' if language=='C' else str(ROOT/'build/rust-mir/toolchain/bin/rustc')
            require(compiler==expected and sha(__import__('pathlib').Path(compiler))==config['compiler_sha256'],'Compiler identity mismatch')
            flags=[f.replace('$REPO',str(ROOT)) for f in config['flags']]
            require(not any('instrument-mcount' in f or 'emit=mir' in f or 'emit=llvm' in f or f=='-emit-llvm' for f in flags),'Smoke policy permits native compilation only')
            env=os.environ.copy()
            for key in list(env):
                if key.startswith('MIR_PROBE_') or key in ('RUSTC_WRAPPER','RUSTC_WORKSPACE_WRAPPER','RUSTFLAGS','CFLAGS'):env.pop(key,None)
            if language=='Rust':
                verify_std(config)
                env.update(config['environment'])
                env['LD_LIBRARY_PATH']=str(ROOT/'build/rust-mir/toolchain/lib')+':'+str(ROOT/'build/rust-mir/toolchain/lib/rustlib/x86_64-unknown-linux-gnu/lib')
            directory=output/pair['pair_id']/language;directory.mkdir(parents=True)
            executable=directory/'fixture'
            command=[compiler,pair[prefix+'_source'],*flags]
            if language=='Rust':command+=['--crate-name','calibration_'+pair['pair_id']]
            command+=['-o',str(executable)]
            compiled=subprocess.run(command,cwd=ROOT,env=env,capture_output=True,text=True,timeout=180)
            row={'pair_id':pair['pair_id'],'language':language,'source_sha256':pair[prefix+'_source_sha256'],
                 'command':[a.replace(str(ROOT),'$REPO') for a in command],
                 'compiler_returncode':compiled.returncode,'compiler_stdout':compiled.stdout.replace(str(ROOT),'$REPO'),
                 'compiler_stderr':compiled.stderr.replace(str(ROOT),'$REPO'),'executions':[]}
            if compiled.returncode==0:
                for runtime in pair['runtime_inputs']:
                    ran=subprocess.run([str(executable),*runtime['arguments']],input=runtime['stdin'],cwd=ROOT,env=env,capture_output=True,text=True,timeout=30)
                    row['executions'].append({'configuration':runtime['id'],'arguments':runtime['arguments'],
                        'exit_code':ran.returncode,'stdout':ran.stdout,'stderr':ran.stderr,
                        'passed':ran.returncode==runtime['expected_exit_code'] and ran.stdout==runtime['expected_stdout'] and ran.stderr==runtime['expected_stderr'],
                        'callbacks_measured':False})
            row['passed']=compiled.returncode==0 and len(row['executions'])==len(pair['runtime_inputs']) and all(r['passed'] for r in row['executions'])
            records.append(row)
            (directory/'smoke.json').write_text(json.dumps(row,sort_keys=True,indent=2)+'\n')
            print(pair['pair_id'],language,'PASS' if row['passed'] else 'FAIL',flush=True)
    after=verify_instruments();validate()
    result={'kind':'ordinary_compile_run_only','semantic_analyzers_invoked':False,'call_edges_traced':False,'depths_calculated':False,
            'calibration_fixture_bundle_sha256':frozen['calibration_fixture_bundle_sha256'],
            'compilations_passed':sum(r['compiler_returncode']==0 for r in records),'compilations_total':30,
            'runtime_configurations_passed':sum(e['passed'] for r in records for e in r['executions']),
            'runtime_configurations_total':sum(len(p['runtime_inputs'])*2 for p in manifest['pairs']),
            'passed':all(r['passed'] for r in records),'records':records,'instrument_before':before,'instrument_after':after}
    (output/'results.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
    require(result['passed'],'Smoke compilation/execution failed; inspect compiler diagnostics only')
    print('Ordinary smoke tests passed; no semantic measurements performed.',flush=True)


if __name__=='__main__':main()
