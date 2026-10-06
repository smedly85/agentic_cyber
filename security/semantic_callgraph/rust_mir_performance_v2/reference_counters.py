"""Optional observational counters in an in-memory reference AST copy.

The frozen file is never written. This separate counting pass is not used for
baseline timing; its scientific output must equal the uninstrumented reference.
"""
import ast
from collections import Counter
from common import REFERENCE,REFERENCE_SHA,sha

def increment(name,expression='1'):
    return ast.parse(f'_perf_counts[{name!r}] += {expression}').body[0]

class Observe(ast.NodeTransformer):
    def __init__(self):self.functions=[]
    def visit_FunctionDef(self,node):
        self.functions.append(node.name);self.generic_visit(node);self.functions.pop()
        labels={'collapse':'collapse_calls','copy':'copy_calls','store':'store_calls'}
        if node.name in labels:node.body.insert(0,increment(labels[node.name]))
        return node
    def visit_For(self,node):
        self.generic_visit(node)
        name=node.target.id if isinstance(node.target,ast.Name) else None
        if name=='_':node.body.insert(0,increment('sweeps'))
        elif name=='constraint':node.body.insert(0,increment('constraints_processed'))
        elif name=='site':node.body.insert(0,increment('callsites_processed'))
        elif name=='cell' and self.functions[-1:] == ['store']:
            node.body.insert(0,increment('plain_tokens_considered','len(incoming)'))
        elif name=='key' and self.functions[-1:] == ['collapse']:
            node.body[:0]=[increment('collapse_members_scanned'),increment('collapse_tokens_scanned','len(values[key])')]
        elif name in ('key','cell') and isinstance(node.iter,ast.Call) and isinstance(node.iter.func,ast.Name) and node.iter.func.id=='list':
            node.body.insert(0,increment('field_members_scanned'))
        return node
    def visit_If(self,node):
        self.generic_visit(node)
        test=ast.unparse(node.test)
        if test == 'base not in collapsed':node.body.insert(0,increment('first_collapses'))
        if test == "kind == 'pointer_metadata'":node.body.insert(0,increment('metadata_queries'))
        return node
    def visit_AugAssign(self,node):
        if self.functions[-1:] == ['store'] and isinstance(node.target,ast.Name) and node.target.id=='changed':
            return [node,increment('points_to_additions','len(values[cell]) - old')]
        return node
    def visit_comprehension(self,node):
        self.generic_visit(node)
        filtered=bool(node.ifs)
        container=node.iter
        token_container=(isinstance(container,ast.Name) and container.id in ('incoming','receiver')) or (
            isinstance(container,ast.Subscript) and isinstance(container.value,ast.Name) and container.value.id=='values')
        if filtered and token_container:
            node.iter=ast.Call(func=ast.Name(id='_observe_tokens',ctx=ast.Load()),args=[container],keywords=[])
        return node

def make_reference():
    assert sha(REFERENCE)==REFERENCE_SHA
    counts=Counter()
    def tokens(container):
        counts['token_filter_queries']+=1;counts['token_filter_tokens_scanned']+=len(container)
        return container
    tree=Observe().visit(ast.parse(REFERENCE.read_text()));ast.fix_missing_locations(tree)
    namespace={'__name__':'security.semantic_callgraph.rust_mir._observed_reference',
               '__package__':'security.semantic_callgraph.rust_mir','_perf_counts':counts,'_observe_tokens':tokens}
    exec(compile(tree,str(REFERENCE), 'exec'),namespace)
    return namespace['analyze'],counts
