"""Run only source/schema/hash tamper controls and persist their evidence."""
import subprocess
import sys
import xml.etree.ElementTree as ET
from validate_corpus import HERE, ROOT, validate, sha
from revise_preregistration import write

def main():
    frozen=validate()
    report=ROOT/'build/cross-language-calibration-corpus-smoke/revision-validator.xml'
    report.parent.mkdir(parents=True,exist_ok=True)
    command=[sys.executable,'-m','pytest','-q','tests/test_calibration_corpus.py','tests/test_calibration_runtime_provenance.py','--junitxml',str(report)]
    result=subprocess.run(command,cwd=ROOT,capture_output=True,text=True)
    suites=ET.parse(report).getroot().findall('testsuite')
    counts={key:sum(int(s.get(key,0)) for s in suites) for key in ('tests','failures','errors','skipped')}
    write(HERE/'validator_test_results.json',{'kind':'source_only_validator_tests','command':command,
        'exit_code':result.returncode,'passed':counts['tests']-counts['failures']-counts['errors']-counts['skipped'],
        'failed':counts['failures']+counts['errors'],'skipped':counts['skipped'],
        'observed_summary':result.stdout,'stderr':result.stderr,
        'calibration_fixture_bundle_sha256':frozen['calibration_fixture_bundle_sha256'],
        'junit_xml':report.relative_to(ROOT).as_posix(),'junit_sha256':sha(report),
        'semantic_analyzers_invoked':False,'depths_calculated':False})
    print(result.stdout)
    if result.returncode:raise SystemExit(result.returncode)

if __name__=='__main__':main()
