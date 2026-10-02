"""Controlled typed-place inclusion prototype. Explicitly NOT an accepted backend.

Consumes rustc API records, never parsed MIR display strings. Unsupported
operations prohibit acceptance; no type-only or dynamic-trace fallback exists.
"""
from collections import defaultdict


def analyze(probe):
    functions={row['instance_identity']:row for row in probe['instances']}
    values=defaultdict(set)
    losses=set()
    sites={}

    def locations(owner,place):
        local,projections=place
        current={(owner,local,())}
        for projection in projections:
            if projection=='deref':
                current={value[1] for cell in current for value in values[cell] if value[0]=='address'}
            elif projection.startswith(('field:','variant:')):
                current={(i,l,p+(projection,)) for i,l,p in current}
            else:
                losses.add((owner,'unsupported_projection'))
                return set()
        return current

    def operand(owner,source):
        if 'function' in source:return {('function',source['function'])}
        if 'place' in source:return set().union(*(values[p] for p in locations(owner,source['place'])))
        return set()

    changed=False
    def store(cells,incoming):
        nonlocal changed
        for cell in cells:
            old=len(values[cell]); values[cell].update(incoming)
            changed |= old!=len(values[cell])

    def copy(owner,destination,source,source_owner=None):
        source_owner=source_owner or owner
        cells=locations(owner,destination)
        store(cells,operand(source_owner,source))
        if 'place' in source:
            # Whole-value copies preserve each typed subfield, not their union.
            for src in locations(source_owner,source['place']):
                for key,incoming in list(values.items()):
                    if key[:2]==src[:2] and key[2][:len(src[2])]==src[2]:
                        suffix=key[2][len(src[2]):]
                        store({(i,l,p+suffix) for i,l,p in cells},incoming)

    converged=False
    for _ in range(256):
        changed=False
        for owner,row in functions.items():
            for constraint in row['constraints']:
                kind=constraint['kind']; dst=constraint['destination']; src=constraint['source']
                if kind=='copy':copy(owner,dst,src)
                elif kind=='reference':
                    store(locations(owner,dst),{('address',p) for p in locations(owner,src['place'])})
                elif kind=='aggregate':
                    # Only the untagged field case is represented by this probe.
                    # Enum/downcast layout is not silently claimed supported.
                    losses.add((owner,'aggregate_variant_kind_not_exported'))
                    for index,field in enumerate(src):
                        copy(owner,[dst[0],dst[1]+['field:'+str(index)]],field)
                else:losses.add((owner,kind))
            for site in row['calls']:
                key=(owner,site['block'])
                if site['status'] in ('resolved_instance','drop_instance'):
                    targets={site['target']}
                elif site['status']=='unresolved_function_pointer':
                    targets={v[1] for v in operand(owner,site['callee_value']) if v[0]=='function'}
                else:
                    targets=set(); losses.add((owner,site['status']))
                previous=sites.setdefault(key,set())
                old=len(previous); previous.update(targets); changed |= old!=len(previous)
                for target in targets:
                    if target not in functions:
                        losses.add((owner,'external_or_unexported_body')); continue
                    if 'arguments' not in site:continue
                    for index,arg in enumerate(site['arguments'],1):
                        copy(target,[index,[]],arg,owner)
                    copy(owner,site['destination'],{'place':[0,[]]},target)
        if not changed:
            converged=True;break
    return {'accepted_backend':False,'converged':converged,
            'analysis_class':'flow-insensitive context-insensitive inclusion prototype',
            'sites':[{'owner':owner,'block':block,'targets':sorted(targets)} for (owner,block),targets in sorted(sites.items())],
            'unsupported_operations':[{'instance':owner,'reason':reason} for owner,reason in sorted(losses)],
            'precision_policy':'Unsupported operations reject acceptance; no silent exactness claimed'}
