"""Controlled-only final extraction, strict adjudication, freeze check and traces."""
import argparse
import subprocess
import sys
from prepare import ROOT,HERE


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--label',required=True);args=parser.parse_args()
    assert args.label.replace('-','').isalnum()
    commands=[('continuation_validation.py',['--label',args.label]),
              ('adjudicate_core.py',['--label',args.label]),
              ('complete_validation.py',['--label',args.label]),
              ('cast_gate_audit.py',['--compare',args.label]),
              ('dynamic_validation.py',['--static-label',args.label,'--label',args.label])]
    for script,options in commands:
        subprocess.run([sys.executable,str(HERE/script),*options],cwd=ROOT,check=True)


if __name__=='__main__':main()
