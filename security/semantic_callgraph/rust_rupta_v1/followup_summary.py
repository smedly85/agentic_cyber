"""Summarize saved follow-up evidence; never runs historical analysis."""
import collections
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
TRIAL = ROOT / 'build/rupta-v1/drop-trial'
MODERN = TRIAL / 'compatibility'


def main():
    records = json.loads((MODERN/'modern-validation-results.json').read_text())
    summary = {}
    for mode in ('ander', 'cs'):
        first = [r for r in records if r['mode']==mode and r['repeat']==1]
        second = [r for r in records if r['mode']==mode and r['repeat']==2]
        assert len(first)==len(second)==38
        assert len({r['program'] for r in first})==35
        assert all(r['status']=='completed' and r['evaluation']['required_expectations_passed'] for r in first+second)
        sites = [s for r in first for s in r['evaluation']['sites'] if s['expected']]
        assert len(sites)==23 and all(s['passed'] for s in sites)
        assert all(r['deterministic'] for r in second)
        summary[mode] = dict(programs_passed=35, programs_total=35, exact_designated_targets=23,
                             designated_targets=23, deterministic_repeats=38)
    for r in records:
        out = MODERN/'modern-validation'/f"run-{r['repeat']}"/r['program']/r['mode']/r['entry']
        rss = re.search(r'Maximum resident set size \(kbytes\): (\d+)', (out/'resources.txt').read_text())
        r['peak_rss_kib'] = int(rss[1]) if rss else None
        graph = json.loads((out/'context.graph.json').read_text())
        r['context_maximum_finite_shortest_path_depth'] = max(f['raw_call_depth'] for f in graph['functions'] if f['reachable_from_entry'])
        r['artifact_directory'] = str(out.relative_to(ROOT))
    pilot = json.loads((MODERN/'historical-pilot/result.json').read_text())
    raw = json.loads((MODERN/'historical-pilot/normalized.json').read_text())
    names = {f['identity']:f['name'] for f in raw['functions']}
    unresolved = [{**s, 'caller_name':names[s['caller']]} for s in raw['unresolved_indirect_callsites']]
    counts = collections.Counter((s['kind'], Path(s['callsite'].get('file','')).name, s['callsite'].get('line')) for s in unresolved)
    result = {
        'instrument':'separate modern fork plus Drop/reporting overlay',
        'provenance':json.loads((MODERN/'modern-provenance.json').read_text()),
        'summary':summary, 'records':records,
        'historical_build':json.loads((MODERN/'historical-build/result.json').read_text()),
        'pilot':pilot, 'pilot_unresolved_callsites':unresolved,
        'pilot_unresolved_groups':[dict(kind=k[0], file_basename=k[1], line=k[2], count=v) for k,v in sorted(counts.items())],
        'preservation':json.loads((TRIAL/'preservation-after.json').read_text()),
        'accepted_historical_measurement':False,
        'bulk_historical_gate':'blocked pending pilot mapping and graph-coverage review; unresolved inventory is not globally complete',
    }
    (HERE/'followup_results.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'summary':summary,'unresolved_groups':result['pilot_unresolved_groups'],'coverage':pilot['coverage']},indent=2))


if __name__=='__main__':
    main()
