"""Exact source/DefPath/span resolver copied from frozen historical orchestration. No solver import."""
import re

def source_line(row):
    match=re.search(r':(\d+):\d+:',row.get('source',''))
    return int(match[1]) if match else None

def definition_matches(row,checkout,source,function,crate):
    if row.get('defining_crate')!=crate or row.get('compiler_generated'):return False
    if source not in row.get('source',''):return False
    line=source_line(row)
    if line is None:return False
    lines=(checkout/source).read_text().splitlines()
    short=function.split('::')[-1]
    if line>len(lines) or not re.search(r'\bfn\s+'+re.escape(short)+r'\s*(?:<|\()',lines[line-1]):return False
    path=row.get('def_path','')
    if '::{closure' in path:return False
    if '::' in function:
        owner=re.sub(r'<.*>','',function.rsplit('::',1)[0])
        if not re.search(r'(?<![A-Za-z0-9_])'+re.escape(owner)+r'(?![A-Za-z0-9_])',path):return False
    return path.split('::')[-1]==short or bool(re.search(r'::'+re.escape(short)+r'::<',path))
