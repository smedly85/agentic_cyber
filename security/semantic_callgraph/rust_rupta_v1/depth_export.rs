// Experimental depth-study sidecar for the pinned RUPTA checkout.
// Does not change analysis, target sets, or contexts.
use crate::graph::call_graph::{CallGraph, CGFunction, CGCallSite};
use crate::mir::analysis_context::AnalysisContext;
use crate::mir::call_site::BaseCallSite;
use crate::mir::function::FuncId;
use petgraph::visit::EdgeRef;
use serde_json::{json, Value};

fn source(acx: &AnalysisContext, span: rustc_span::Span) -> Value {
    if span.is_dummy() { return Value::Null; }
    let sm = acx.tcx.sess.source_map();
    let lo = sm.lookup_char_pos(span.lo());
    let hi = sm.lookup_char_pos(span.hi());
    json!({"file":lo.file.name.prefer_local().to_string(), "line":lo.line,
           "column":lo.col.0+1, "end_line":hi.line, "end_column":hi.col.0+1})
}

pub fn dump<F, S>(acx: &AnalysisContext, cg: &CallGraph<F,S>)
where F: CGFunction + Into<FuncId>, S: CGCallSite + Into<BaseCallSite> {
    let Some(path) = &acx.analysis_options.call_graph_output else { return; };
    let mut nodes = Vec::new();
    let mut functions = Vec::new();
    let mut visited = std::collections::HashSet::new();
    let mut entries = Vec::new();
    for f in cg.reach_funcs_iter() {
        let id: FuncId = f.into();
        let fr = acx.get_function_reference(id);
        let node = format!("{:?}", f);
        if fr.def_id == acx.entry_point { entries.push(node.clone()); }
        nodes.push(json!({"id":node, "function":format!("{:?}",id)}));
        if visited.insert(id) {
            functions.push(json!({"id":format!("{:?}",id), "name":fr.to_string(),
                "def_id":format!("{:?}",fr.def_id),
                "def_path_hash":format!("{:?}",acx.tcx.def_path_hash(fr.def_id)),
                "generic_args":format!("{:?}",fr.generic_args),
                "promoted":format!("{:?}",fr.promoted),
                "source":source(acx, acx.tcx.def_span(fr.def_id)),
                "body_available":acx.function_mir(id).is_some(),
                "special_model":acx.special_functions.contains(&id),
                "drop_glue":acx.tcx.lang_items().drop_in_place_fn()==Some(fr.def_id)}));
        }
    }
    let mut edges = Vec::new();
    for e in cg.graph.edge_references() {
        let base: BaseCallSite = e.weight().callsite.into();
        edges.push(json!({"caller":format!("{:?}",cg.graph[e.source()].func),
            "callee":format!("{:?}",cg.graph[e.target()].func),
            "location":format!("{:?}",base.location)}));
    }
    // A recognized site exists even when no points-to target was found.
    // Each reachable context processes the same function-PAG site inventory.
    let mut sites = Vec::new();
    for f in cg.reach_funcs_iter() {
        let id: FuncId = f.into();
        for (base, kind) in &cg.callsite_to_type {
            if base.func != id { continue; }
            let caller = format!("{:?}",f);
            let loc = format!("{:?}",base.location);
            let span = acx.function_mir(id).map(|body| {
                let block = &body.basic_blocks[base.location.block];
                if base.location.statement_index < block.statements.len() {
                    block.statements[base.location.statement_index].source_info.span
                } else { block.terminator().source_info.span }
            });
            let targets: Vec<_> = edges.iter().filter(|e| e["caller"]==caller && e["location"]==loc)
                .map(|e| e["callee"].clone()).collect();
            sites.push(json!({"caller":caller,"location":loc,"kind":format!("{:?}",kind),
                "source":span.map(|s|source(acx,s)),"targets":targets}));
        }
    }
    // FuncId(0) is not assumed: use the actual first reachable node as root,
    // and verify its DefId is the configured compiler entry.
    let root = nodes.first().expect("analysis without reachable entry")["id"].clone();
    assert!(entries.iter().any(|s| *s == root.as_str().unwrap()));
    let value = json!({"schema":1,"entry":root,"entry_def_id":format!("{:?}",acx.entry_point),
        "functions":functions,"nodes":nodes,"edges":edges,"callsites":sites,
        "unresolved_scope":"recognized indirect callsites only; not a soundness certificate"});
    std::fs::write(format!("{}.depth.json",path),serde_json::to_vec_pretty(&value).unwrap()).unwrap();
}
