"""Publish an explicitly incomplete, controlled-only feasibility milestone."""
import hashlib
import json
from pathlib import Path
from prepare import ROOT,HERE,require_c
from graph import export_partial


def read(path):return json.loads(path.read_text())
def write(name,value):(HERE/name).write_text(json.dumps(value,indent=2,sort_keys=True)+'\n')
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    require_c()
    feasibility=read(HERE/'feasibility.json')
    inclusion=read(HERE/'inclusion_probe.json')
    write('partial_graph.json',export_partial(feasibility,inclusion))
    c=read(ROOT/'build/rust-mir/c-restoration/regression/results.json')
    write('c_regression.json',c)
    write('dynamic_trace_results.json',{'status':'not_run','accepted':False,
        'reason':'No complete static may-call graph; dynamic soundness gate not satisfied'})
    pairs=['direct_chain','recursion','single_pointer','multi_pointer','first_field','non_first_field',
           'stack_copy','heap_struct','generic_specialization','static_dispatch','dyn_vtable',
           'closure_context','library_callback','mixed_stack_static','mixed_stack_heap']
    write('calibration_results.json',{'status':'not_run','accepted':False,
        'preregistration_sha256':sha(HERE/'PREREGISTRATION.md'),
        'pairs':[{'pair':p,'status':'not_run'} for p in pairs],
        'target_set_size_distribution':None,
        'reason':'Incomplete Rust pointer/dyn/heap/unsafe semantics; no cross-language equivalence claimed'})
    record={'status':'MIR-STOP','milestone':'partial controlled feasibility spike; implementation incomplete',
        'historical_measurement':False,'accepted_backend':False,
        'compiler':feasibility['compiler'],'bootstrap':'RUSTC_BOOTSTRAP=1',
        'flags':feasibility['flags'],'components':read(HERE/'toolchain_acquisition.json'),
        'driver_sha256':sha(HERE/'driver.rs'),
        'driver_binary_sha256':sha(ROOT/'build/rust-mir/probe-build/mir-probe'),
        'c_restoration':read(HERE/'c_restoration.json'),
        'counting_policy':'raw MIR semantic instance edges, including compiled generics and shims; no contraction',
        'probe_deterministic':feasibility['probe_deterministic'],
        'full_suite_determinism':'not_run',
        'blockers':['value-flow dyn dispatch not implemented','heap allocation-site semantics not implemented',
                    'unsafe byte/union conservative merging not implemented','whole-program crate closure not established',
                    'std upstream MIR optimization boundary not calibrated','dynamic traces and C/Rust calibration not run']}
    write('instrument.json',record)
    cache=ROOT/'build/rust-mir'
    evidence=[]
    for name in ('probe','controlled-probe','c-restoration'):
        evidence.extend((cache/name).rglob('*.json'))
    write('evidence_manifest.json',{p.relative_to(ROOT).as_posix():sha(p) for p in sorted(evidence)})
    manifest={p.relative_to(HERE).as_posix():sha(p) for p in sorted(HERE.rglob('*'))
        if p.is_file() and '__pycache__' not in p.parts and p.name!='artifact_manifest.json'}
    write('artifact_manifest.json',manifest)
    print('MIR-STOP: partial feasibility spike, not a validated semantic instrument')


if __name__=='__main__':main()
