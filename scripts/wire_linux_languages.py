"""Apply narrowly scoped standardized-selector integration; historical paths stay intact."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
old='{"c-cp", "c-mv", "c-mkdir", "c-sort"}'
for name in ('lineage_plan.py','stage_test_bundle.py','heldout_judge.py','check_heldout_isolation.py','checkpoint_boundary_gate.py'):
    path=ROOT/'scripts'/name
    text=path.read_text()
    assert 'from linux_utilities_catalog import' not in text
    # All these modules already import pathlib before their first function/class.
    marker=min(i for i in (text.find('\ndef '),text.find('\nclass ')) if i>=0)
    text=text[:marker]+'\nfrom linux_utilities_catalog import SELECTORS as LINUX_SELECTORS, suite_root as linux_suite_root, utility_name\n'+text[marker:]
    text=text.replace(old,'LINUX_SELECTORS')
    if name=='stage_test_bundle.py':
        text=text.replace('suite_root = repo / test_dir','suite_root = linux_suite_root(repo, utility, test_dir)')
        text=text.replace('files["config.json"] = bundle_config',
            'if utility in LINUX_SELECTORS:\n        files["judge_candidate.sh"] = (repo / test_dir / "judge_candidate.sh").read_bytes()\n\n    files["config.json"] = bundle_config')
        text=text.replace('if utility == "c-sort":','if utility in LINUX_SELECTORS and utility_name(utility) == "sort":')
        text=text.replace('str(suite_root),\n        tuple(checkpoint',
            'str(suite_root),\n        utility,\n        (repo / test_dir / "judge_candidate.sh").read_bytes() if utility in LINUX_SELECTORS else b"",\n        tuple(checkpoint')
    elif name=='check_heldout_isolation.py':
        text=text.replace('return repo / plan["test_dir"], plan','return linux_suite_root(repo, utility, plan["test_dir"]), plan')
    elif name=='checkpoint_boundary_gate.py':
        text=text.replace('\ndef run_probe(', '\nfor _selector in LINUX_SELECTORS:\n    PROBES[_selector] = PROBES["c-" + utility_name(_selector)]\n\n\ndef run_probe(')
        text=text.replace('excluded[utility], excluded[utility]', 'excluded["c-" + utility_name(utility)], excluded["c-" + utility_name(utility)]')
        text=text.replace('if utility == "c-sort":','if utility in LINUX_SELECTORS and utility_name(utility) == "sort":')
    elif name=='lineage_plan.py':
        text=text.replace('"scripts/docker_benchmark_worker.py",','"scripts/docker_benchmark_worker.py",\n            "scripts/linux_utilities_catalog.py",\n            "scripts/python_candidate.py",\n            "docker/linux-utilities/Rust.Dockerfile",')
        text=text.replace('"benchmark": "linux-utilities", "required_platform": "Linux",','"benchmark": "linux-utilities", "protocol_version": 1, "required_platform": "Linux",')
    path.write_text(text)
path=ROOT/'scripts/linux_benchmark_isolation.py'
text=path.read_text().replace("selector != 'c-sort'", "selector not in ('c-sort','rust-sort','py-sort')").replace("selector == 'c-sort'", "selector in ('c-sort','rust-sort','py-sort')")
path.write_text(text)
path=ROOT/'scripts/run_lineage_experiment.sh'; text=path.read_text()
selectors='c-cp|c-mv|c-mkdir|c-sort|rust-cp|rust-mv|rust-mkdir|rust-sort|py-cp|py-mv|py-mkdir|py-sort'
text=text.replace('case "$UTILITY" in\n    c-cp|c-mv|c-mkdir|c-sort)', 'LINUX_BENCHMARK=0\ncase "$UTILITY" in\n    '+selectors+')\n        LINUX_BENCHMARK=1')
text=text.replace('if [[ "$DRY_RUN" -eq 0 && "$SOURCE_PATH" == *.rs ]]; then','if [[ "$DRY_RUN" -eq 0 && "$SOURCE_PATH" == *.rs && "$LINUX_BENCHMARK" -eq 0 ]]; then')
text=text.replace('if [[ "$UTILITY" != c-cp && "$UTILITY" != c-mv && "$UTILITY" != c-mkdir && "$UTILITY" != c-sort &&','if [[ "$LINUX_BENCHMARK" -eq 0 &&')
path.write_text(text)
path=ROOT/'scripts/run_experiment.sh'; text=path.read_text().replace('c_selector','linux_selector')
paths='|'.join('src/'+s.replace('-','_')+'/*' for s in selectors.split('|'))
text=text.replace('src/c_cp/*|src/c_mv/*|src/c_mkdir/*|src/c_sort/*)',paths+')')
text=text.replace('if [[ "$SOURCE_PATH" == *.rs ]]; then','if [[ "$SOURCE_PATH" == *.rs && -z "${linux_selector:-}" ]]; then')
text=text.replace('if [[ "$SOURCE_PATH" == *.py || "$SOURCE_PATH" == src/c_cp/* ||', 'if [[ -n "${linux_selector:-}" || "$SOURCE_PATH" == *.py || "$SOURCE_PATH" == src/c_cp/* ||')
text=text.replace('C benchmark requires canonical Docker commands','Linux benchmark requires canonical Docker commands')
path.write_text(text)
print('Wired shared suites, all selectors, and mandatory Docker controller paths')
