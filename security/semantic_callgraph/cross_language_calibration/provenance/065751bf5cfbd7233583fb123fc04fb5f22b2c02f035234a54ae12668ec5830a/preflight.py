"""Freeze calibration prerequisites without inventing paired fixtures or results."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
MIR=ROOT/'security/semantic_callgraph/rust_mir'
BASE=ROOT/'build/rust-mir'


def read(path):return json.loads(path.read_text())
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def write(name,value):(HERE/name).write_text(json.dumps(value,sort_keys=True,indent=2)+'\n')
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def main():
    assert not (HERE/'instrument_fingerprints.json').exists(), 'Never overwrite the calibration-start freeze'
    instrument=read(MIR/'instrument.json')
    assert instrument['status']=='MIR-CORE-GO'
    assert instrument['complete_semantic_passed']==instrument['controlled_static_assertions_passed']==instrument['dynamic_soundness_passed']==31
    assert instrument['controlled_deterministic'] and instrument['dynamic_deterministic']
    rust_files=['driver.rs','inclusion.py','body_ledger.py','graph.py','std_config.py',
                'dynamic_validation.py','trace_compare.py','runtime_mcount.S','runtime_trace.c',
                'instrument.json','PREREGISTRATION.md','artifact_manifest.json']
    rust_sources={str((MIR/n).relative_to(ROOT)):sha(MIR/n) for n in rust_files}
    assert sha(MIR/'driver.rs')==instrument['driver_sha256']
    assert sha(MIR/'inclusion.py')==instrument['inclusion_sha256']
    for name,expected in read(MIR/'artifact_manifest.json').items():
        assert sha(MIR/name)==expected, name
    evidence={name:{**record,'verified':sha(ROOT/record['path'])==record['sha256']} for name,record in instrument['evidence'].items()}
    assert all(r['verified'] for r in evidence.values())
    env=os.environ.copy();env['LD_LIBRARY_PATH']=str(BASE/'toolchain/lib')+':'+str(BASE/'toolchain/lib/rustlib/x86_64-unknown-linux-gnu/lib')
    rust_version=subprocess.check_output([str(BASE/'toolchain/bin/rustc'),'-vV'],env=env,text=True)
    clang_version=subprocess.check_output(['/usr/lib/llvm-21/bin/clang','--version'],text=True)
    assert 'rustc 1.93.0' in rust_version and 'LLVM version: 21.1.8' in rust_version
    assert 'clang version 21.1.8' in clang_version
    helper=ROOT/'build/semantic-toolchain/SVF/Release-build/bin/semantic-callgraph-svf'
    helper_sha=sha(helper)
    assert helper_sha=='ca8ce8cd9e7e264dd8db7e8e8d656765af876db3fbec878da4de0edcc882a7d2'
    c_sources={name:sha(ROOT/name) for name in ['security/semantic_callgraph/backend.py','security/semantic_callgraph/native/semantic_callgraph_svf.cpp']}
    svf_cmake=ROOT/'build/semantic-toolchain/SVF/CMakeLists.txt'
    assert 'VERSION 3.4' in svf_cmake.read_text()
    rust={'sources':rust_sources,'compiler_version':rust_version,
          'compiler_sha256':sha(BASE/'toolchain/bin/rustc'),
          'driver_binary_path':'build/rust-mir/continuation/cast-final-v2/driver',
          'driver_binary_sha256':sha(BASE/'continuation/cast-final-v2/driver'),
          'std_configuration':read(BASE/'continuation/cast-final-v2/std_configuration.json'),
          'controlled_evidence':evidence,'primary_metric':'shortest raw semantic Instance edge count; no shim contraction',
          'complete_static_gate':31,'semantic_assertions':31,'dynamic_traces':31,'deterministic':True}
    rust['calibration_start_sha256']=digest(rust)
    c={'sources':c_sources,'compiler_version':clang_version,'compiler_sha256':sha(Path('/usr/lib/llvm-21/bin/clang')),
       'svf_version':'3.4','svf_version_evidence_sha256':sha(svf_cmake),'analysis':'AndersenWaveDiff',
       'helper_options':['-stat=false','-ff-eq-base'],'helper_path':str(helper.relative_to(ROOT)),
       'helper_sha256':helper_sha,'primary_metric':'shortest static semantic may-call edge count'}
    write('instrument_fingerprints.json',{'schema_version':1,'phase':'calibration_start','C':c,'Rust':rust,
          'calibration_executed':False,'backend_modifications':[]})
    prior=read(MIR/'calibration_results.json')
    prereg=(MIR/'PREREGISTRATION.md').read_text()
    table=prereg.split('## Cross-language pairs and expected relationships',1)[1].split('Compare target-set',1)[0]
    rows=[line.strip().strip('|').split('|') for line in table.splitlines() if line.startswith('|')][2:]
    assert len(rows)==len(prior['pairs'])==15
    expectations=[{'pair':p['pair'],'category':r[0].strip(),'verbatim_expectation':r[1].strip(),
                   'frozen_c_source':None,'frozen_rust_source':None,'source_pair_manifest':None}
                  for p,r in zip(prior['pairs'],rows)]
    write('preregistered_expectations.json',{'source':'security/semantic_callgraph/rust_mir/PREREGISTRATION.md',
          'source_sha256':sha(MIR/'PREREGISTRATION.md'),'pairs':expectations,
          'fixture_resolution_status':'missing_frozen_paired_source_manifest',
          'note':'The 15 categories and relationships are registered. No paired source paths or source hashes occur in that registration or its not-run calibration record. No substitutes selected.'})
    (HERE/'PREREGISTRATION.snapshot.md').write_bytes((MIR/'PREREGISTRATION.md').read_bytes())
    print('Frozen instruments. Rust calibration-start SHA-256:',rust['calibration_start_sha256'],flush=True)


if __name__=='__main__':main()
