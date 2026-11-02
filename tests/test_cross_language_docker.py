"""Temporary transport controls only: no utility implementation or lineage seed."""
import base64
import contextlib
import gzip
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import docker_benchmark as docker
import checkpoint_boundary_gate as gate


class CrossLanguageDocker(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def build(self,language,text):
        source=self.root/('probe.'+{'rust':'rs','py':'py'}[language])
        source.write_text(text); binary=self.root/('probe-'+language)
        self.assertEqual(docker.compile_source(source,binary),0)
        return binary

    def test_real_rust_and_python_runtime_isolation_and_io(self):
        programs={
          'rust':r'''use std::{fs,io::{self,Read,Write}};
fn main(){
 for p in ["/opt/gnu/bin/cp","/bin/cp","/work","/proc/1/environ","/var/run/docker.sock","/tmp/harness/runner.py","/output","/etc/shadow"] { assert!(!std::path::Path::new(p).exists()); }
 assert!(fs::write("locked",b"bad").is_err());
 let mut data=Vec::new();io::stdin().read_to_end(&mut data).unwrap();
 fs::write("out",&data).unwrap(); std::os::unix::fs::symlink("out","link").unwrap();
 io::stdout().write_all(&data).unwrap();
}''',
          'py':'''import os,sys,socket,hashlib,shutil,pathlib,stat
assert os.getuid()==1000 and os.getgid()==1000
for p in ['/opt/gnu/bin/cp','/bin/cp','/work','/proc/1/environ','/var/run/docker.sock','/tmp/harness/runner.py','/output','/etc/shadow']:
    assert not os.path.exists(p)
try: open('locked','wb'); raise AssertionError('permissions bypassed')
except PermissionError: pass
try: os.setuid(0); raise AssertionError('root gained')
except PermissionError: pass
s=socket.socket(); s.settimeout(1)
try: s.connect(('1.1.1.1',80)); raise AssertionError('network accessible')
except OSError: pass
finally: s.close()
data=sys.stdin.buffer.read(); pathlib.Path('out').write_bytes(data); os.symlink('out','link'); sys.stdout.buffer.write(data)
'''}
        data=b'case transport\x00\xff\n'
        for language,text in programs.items():
            binary=self.build(language,text)
            result=docker.execute_case(language+'-cp',binary.read_bytes(),{
                'args':[],'stdin_b64':base64.b64encode(data).decode(),
                'fixture':[{'path':'locked','type':'file','contents_b64':'b2s=','mode':'0444'}]})['result']
            self.assertEqual(result['exit_code'],0,result)
            self.assertEqual(base64.b64decode(result['stdout']['$bytes']),data)
            self.assertEqual(result['modes']['out']['sha256'],hashlib.sha256(data).hexdigest())
            self.assertEqual(result['modes']['locked']['sha256'],hashlib.sha256(b'ok').hexdigest())
            self.assertEqual(result['modes']['link']['type'],'symlink')

    def test_syntax_failures_and_empty_python_are_candidate_failures(self):
        for suffix,text in [('rs','invalid Rust'),('py','def broken(:'),('py','')]:
            source=self.root/('invalid.'+suffix); source.write_text(text)
            self.assertEqual(docker.compile_source(source,self.root/'invalid'),1)

    def test_python_and_rust_timeouts(self):
        for language,text in [('py','while True: pass\n'),('rust','fn main(){loop {std::hint::spin_loop();}}')]:
            binary=self.build(language,text)
            result=docker.execute_case(language+'-cp',binary.read_bytes(),{'args':[],'timeout':1})['result']
            self.assertTrue(result['timed_out'])

    def test_all_thirty_language_checkpoint_boundaries(self):
        for language in ('rust','py'):
            for utility in ('cp','mv','mkdir','sort'):
                status=2 if utility=='sort' else 1
                text=('fn main(){eprintln!("unknown option");std::process::exit('+str(status)+');}' if language=='rust'
                      else 'import sys\nsys.stderr.write("unknown option\\n")\nsys.exit('+str(status)+')\n')
                binary=self.build(language,text); selector=language+'-'+utility
                for checkpoint in gate.load_manifest(ROOT,selector)['checkpoints']:
                    self.assertTrue(gate.evaluate(ROOT,selector,checkpoint['id'],binary)['passed'],(selector,checkpoint['id']))

    def test_sixty_runtime_mutation_controls(self):
        for language in ('rust','py'):
            binary=self.build(language,'fn main(){}' if language=='rust' else 'pass\n')
            for utility in ('cp','mv','mkdir','sort'):
                selector=language+'-'+utility
                suite=docker.suite_root(ROOT,selector)
                manifest=gate.load_manifest(ROOT,selector)
                for hidden in (False,True):
                    corpus=json.loads(gzip.decompress((suite/('heldout/heldout_cases.json.gz' if hidden else 'suites/linux.json.gz')).read_bytes()))['cases']
                    for checkpoint in manifest['checkpoints']:
                        case=dict(next(c for c in corpus if not c.get('flags') and c.get('check','golden')=='golden'))
                        case['exit_code']=73
                        with contextlib.redirect_stdout(io.StringIO()):
                            verdict=docker.judge(selector,binary,checkpoint['implemented_flags'],hidden=hidden,cases_override=[case])
                        self.assertEqual(verdict['status'],1,(selector,checkpoint['id'],hidden))
                        self.assertEqual(verdict['report']['counts'].get('FAIL'),1)

    def test_permissive_boundaries_and_missing_docker_fail_closed(self):
        for language in ('rust','py'):
            binary=self.build(language,'fn main(){}' if language=='rust' else 'pass\n')
            self.assertFalse(gate.evaluate(ROOT,language+'-cp','000',binary)['passed'])
            with patch.object(docker.subprocess,'run',side_effect=FileNotFoundError('Docker unavailable')) as run:
                with self.assertRaises(docker.InfrastructureError):
                    docker.invoke('compile',{'language':language,'source':''})
                self.assertTrue(all(call.args[0][0]=='docker' for call in run.call_args_list))


if __name__=='__main__': unittest.main()
