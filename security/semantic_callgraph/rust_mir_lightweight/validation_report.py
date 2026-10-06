from common import HERE,OUT,read,write,sha
proof=read(OUT/'validation_summary.json');assert proof['status']=='PASS'
lines=['# Lightweight Rust MIR validation','',
    f"{proof['cases']} existing extracted inputs passed compiler-evidence and BFS checks in two byte-identical graph runs. "
    'No inclusion or points-to solver ran. This validates the narrower known-edge method, not whole-program indirect completeness or C/Rust comparability.', '',
    'Handled construct classes: direct calls and recursion, monomorphized generic calls, statically resolved trait calls, '
    'known concrete closure/Fn Instances, compiler-resolved drop calls, and direct cross-crate calls. '
    'Function pointers stored in locals/fields/heap objects and receiver-dependent dyn/Fn dispatch remain unresolved unless the MIR call itself has a concrete compiler-resolved target. '
    'Unsafe, copy, field and allocation constraints are not interpreted as target evidence. A candidate-implementation inventory never supplies guessed dyn edges.', '',
    'Required concrete-call target paths were checked against the frozen controlled results; all retained call targets also match compiler operands and are subsets of the frozen full-method target sets where those oracles exist. '
    'Every unresolved site is retained. Body-unavailable callees are explicit boundary nodes. BFS path lengths and shortest-distance inequalities were checked.', '',
    '| Case | Entry-reachable unresolved sites | Body boundaries | Controlled designated target paths |',
    '|---|---:|---:|---|']
for r in proof['results']:
    expected=r['controlled_full_method_target_depths'];actual=r['lightweight_target_depths']
    outcome='retained at same depth' if expected and actual==expected else 'some/all full-method paths unresolved' if expected else 'callsite target evidence checked'
    lines.append(f"| {r['id']} | {r['reachable_unresolved_sites']} | {r['reachable_body_boundaries']} | {outcome} |")
lines+=['', 'The initial validation attempt is preserved separately. Its target lookup incorrectly assumed the cross-crate fixture used a function named target; the existing fixture oracle designates cross_target. Only the validation lookup was corrected before these clean reruns; graph implementation and acceptance criteria were unchanged.', '', 'Acceptance: PASS for the explicitly scoped Rust-only retained-call graph. The prior calibration verdict is unchanged. '
    'Unresolved cases are coverage limitations of this method and remain visible in historical statuses.', '']
(HERE/'VALIDATION_REPORT.md').write_text('\n'.join(lines),encoding='utf-8')
write(OUT/'validation_acceptance.json',{'status':'PASS','method':'rust-only-lightweight-v1','report_sha256':sha(HERE/'VALIDATION_REPORT.md'),
    'validation_summary_sha256':sha(OUT/'validation_summary.json'),'scope':'Known compiler-evidenced edges only; unresolved indirect calls not filled in'})
print('Validation report written; Rust-only known-edge scope accepted',flush=True)
