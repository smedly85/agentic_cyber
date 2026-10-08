"""Source/schema/hash validation only: no compiler, analyzer, graph or depth code."""
import argparse
import hashlib
import json
from pathlib import Path
import jsonschema

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
PAIR_IDS=('direct_chain','recursion','single_pointer','multi_pointer','first_field','non_first_field',
          'stack_copy','heap_struct','generic_specialization','static_dispatch','dyn_vtable','closure_context',
          'library_callback','mixed_stack_static','mixed_stack_heap')
METADATA=('fixture_manifest.schema.json','CALIBRATION_PREREGISTRATION.md','source_review.json')


def read(path):return json.loads(path.read_text())
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def canonical(value):return (json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False)+'\n').encode()
def digest(value):return hashlib.sha256(canonical(value)).hexdigest()
def require(condition,message):
    if not condition:raise ValueError(message)


def validate(manifest=None,*,namespace=HERE,repo=ROOT,require_freeze=True):
    manifest=read(namespace/'fixture_manifest.json') if manifest is None else manifest
    jsonschema.Draft202012Validator(read(namespace/'fixture_manifest.schema.json')).validate(manifest)
    ids=[p['pair_id'] for p in manifest['pairs']]
    require(len(set(ids))==15 and tuple(ids)==PAIR_IDS,'Exactly the registered 15 unique pair IDs in order are required')
    require(sha(namespace/'instrument_fingerprints.json')==manifest['instrument_fingerprint_file_sha256'],'Instrument fingerprint reference changed')
    sources={}
    for pair in manifest['pairs']:
        for language,prefix in [('C','c'),('Rust','rust')]:
            path=(repo/pair[prefix+'_source']).resolve()
            require(path.is_relative_to((namespace/'fixtures').resolve()),'Source escaped corpus fixtures')
            require(path.is_file(),'Required source absent: '+str(path))
            actual=sha(path);require(actual==pair[prefix+'_source_sha256'],'Source fingerprint differs: '+str(path))
            sources[pair[prefix+'_source']]=actual
            functions=pair[prefix+'_functions'];lines=path.read_text().splitlines()
            for name,identity in functions.items():
                span=identity['source_span'];start=span['start_line'];end=span['end_line']
                require(identity['source_file']==pair[prefix+'_source'] and identity['language']==language,'Function source/language mismatch')
                require(1<start<=end<len(lines),'Invalid definition span')
                require(lines[start-2].strip()==f'// @function {name} '+identity['semantic_role'],'Definition start anchor mismatch')
                require(lines[end].strip()==f'// @end {name}','Definition end anchor mismatch')
                require(span['end_column']==len(lines[end-1])+1,'Definition end column mismatch')
            require(pair[prefix+'_entry_identity']==functions.get('entry'),'Entry identity absent or mismatched')
            for target in pair[prefix+'_target_identity']:
                require(target==functions.get(target['function_name']),'Target identity absent or mismatched')
            for edge in pair['expected_'+prefix+'_edges']:
                require(edge['caller'] in functions and edge['callee'] in functions,'Expected edge names absent functions')
            site_ids=set()
            for site in pair['expected_'+prefix+'_indirect_targets']:
                require(site['callsite_id'] not in site_ids,'Duplicate indirect callsite');site_ids.add(site['callsite_id'])
                require(site['owner'] in functions,'Callsite owner missing')
                require(all(t in functions for t in site['expected_targets']),'Expected target absent')
                loc=site['source_identity'];n=loc['line']
                require(loc==pair[prefix+'_callsites'].get(site['callsite_id']),'Callsite identity mismatch')
                require(1<n<=len(lines) and lines[n-2].strip()=='// @site '+site['callsite_id'],'Callsite anchor mismatch')
                require(lines[n-1].strip()==loc['source_text'],'Callsite text mismatch')
                owner=functions[site['owner']]['source_span']
                require(owner['start_line']<=n<=owner['end_line'],'Callsite outside owner')
            binding=pair['special_semantics'].get('library_callback_binding',{}).get(language)
            if binding:require(bool(binding['targets']) and all(t in functions for t in binding['targets']),'Library callback target missing')
            for config in pair['runtime_inputs']:
                require(all(t in functions for t in config['expected_observed_callbacks'][language]),'Runtime callback absent')
                require(all(t in functions for t in config['expected_reached_source_targets'][language]),'Runtime target absent')
        for correspondence in pair['application_correspondence']:
            require(correspondence['C'] in pair['c_functions'] and correspondence['Rust'] in pair['rust_functions'],'Application mapping absent')
        require(len({r['id'] for r in pair['runtime_inputs']})==len(pair['runtime_inputs']),'Duplicate runtime configuration')
    actual_sources={p.relative_to(repo).as_posix() for p in (namespace/'fixtures').rglob('*') if p.suffix in ('.c','.rs')}
    require(set(sources)==actual_sources and len(sources)==30,'Exactly 30 referenced C/Rust source files required')
    metadata={name:sha(namespace/name) for name in METADATA}
    payload={'manifest':manifest,'sources':sources,'metadata_sha256':metadata}
    result={'pair_count':15,'source_count':30,'sources':sources,'metadata_sha256':metadata,
            'manifest_sha256':digest(manifest),'calibration_fixture_bundle_sha256':digest(payload)}
    if require_freeze:
        recorded=read(namespace/'fixture_hashes.json')
        require(recorded==result,'Frozen manifest/bundle hash differs')
    return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--freeze',action='store_true');args=parser.parse_args()
    if args.freeze:
        require(not (HERE/'fixture_hashes.json').exists(),'Refusing to overwrite source freeze')
        result=validate(require_freeze=False)
        (HERE/'fixture_hashes.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
    else:result=validate()
    print('15 pairs / 30 sources valid; bundle SHA-256: '+result['calibration_fixture_bundle_sha256'])


if __name__=='__main__':main()
