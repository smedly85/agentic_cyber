"""Post-corpus entry diagnostics; not changes to the preregistered corpus."""
from security.semantic_callgraph.rust_rupta_v1.probe import BASE,HERE,PTA,SYSROOT,run
if __name__=='__main__':
    out=BASE/'entry-diagnostics/invalid-name'
    run([PTA,HERE/'fixtures/direct.rs','--pta-type','ander','--entry-func','no_such_entry',
         '--dump-call-graph',out/'graph.dot','--dump-mir',out/'mir.txt','--dump-dyn-calls',out/'dynamic.txt',
         '--','--crate-name','direct','--edition=2021','--sysroot',SYSROOT,'--emit=metadata','--out-dir',out],out)
    source=BASE/'entry-diagnostics/isolated.rs'
    source.write_text('fn main() {}\n')
    out=BASE/'entry-diagnostics/isolated'
    run([PTA,source,'--pta-type','ander','--dump-call-graph',out/'graph.dot','--dump-mir',out/'mir.txt',
         '--dump-dyn-calls',out/'dynamic.txt','--','--crate-name','isolated','--edition=2021',
         '--sysroot',SYSROOT,'--emit=metadata','--out-dir',out],out)
