//! Controlled API/stage probe. Not an accepted may-call backend.
#![feature(rustc_private)]
extern crate rustc_driver;
extern crate rustc_interface;
extern crate rustc_middle;
extern crate rustc_hir;
extern crate rustc_span;
extern crate rustc_target;
extern crate rustc_data_structures;

use rustc_driver::{Callbacks, Compilation};
use rustc_interface::interface::Compiler;
use rustc_middle::mir::{mono::MonoItem, TerminatorKind, Operand, Place, ProjectionElem, Body, StatementKind, Rvalue};
use rustc_middle::ty::{self, Instance, TyCtxt};
use std::collections::BTreeMap;
use rustc_data_structures::stable_hasher::{HashStable, StableHasher};
use rustc_data_structures::fingerprint::Fingerprint;

fn quoted(value: &str) -> String {
    let mut out=String::from("\"");
    for c in value.chars() {
        match c {
            '"'=>out.push_str("\\\""), '\\'=>out.push_str("\\\\"),
            '\n'=>out.push_str("\\n"), '\r'=>out.push_str("\\r"), '\t'=>out.push_str("\\t"),
            c if c<'\u{20}'=>out.push_str(&format!("\\u{:04x}",c as u32)),
            c=>out.push(c),
        }
    }
    out.push('"'); out
}

fn identity<'tcx>(tcx: TyCtxt<'tcx>, instance: Instance<'tcx>) -> String {
    // Display Instance includes full DefPath, concrete args and shim qualifiers;
    // never persist session-local numeric DefIds or select by bare names.
    let fingerprint:Fingerprint=tcx.with_stable_hashing_context(|mut context| {
        let mut hasher=StableHasher::new();
        instance.hash_stable(&mut context,&mut hasher);
        hasher.finish()
    });
    ty::print::with_no_trimmed_paths!(ty::print::with_no_visible_paths!(ty::print::with_crate_prefix!(
        format!("{fingerprint:?}::{instance}")
    )))
}

struct Probe;

fn place_json(place: Place<'_>) -> String {
    let projections:Vec<String>=place.projection.iter().map(|p|quoted(&match p {
        ProjectionElem::Deref=>"deref".into(),
        ProjectionElem::Field(i,_)=>format!("field:{}",i.index()),
        ProjectionElem::Downcast(_,i)=>format!("variant:{}",i.index()),
        _=>"unsupported_projection".into(),
    })).collect();
    format!("[{},[{}]]",place.local.index(),projections.join(","))
}

fn operand_json<'tcx>(tcx:TyCtxt<'tcx>,instance:Instance<'tcx>,body:&Body<'tcx>,op:&Operand<'tcx>)->String {
    let env=ty::TypingEnv::fully_monomorphized();
    let ty=instance.instantiate_mir_and_normalize_erasing_regions(tcx,env,
        ty::EarlyBinder::bind(op.ty(&body.local_decls,tcx)));
    if let ty::FnDef(def,args)=*ty.kind() {
        if !tcx.is_closure_like(def) {
            if let Some(target)=Instance::resolve_for_fn_ptr(tcx,env,def,args) {
                return format!("{{\"function\":{}}}",quoted(&identity(tcx,target)));
            }
        }
    }
    match op {
        Operand::Copy(p)|Operand::Move(p)=>format!("{{\"place\":{}}}",place_json(*p)),
        _=>"{\"unmodeled_constant\":true}".into(),
    }
}

impl Callbacks for Probe {
    fn after_analysis<'tcx>(&mut self, _: &Compiler, tcx: TyCtxt<'tcx>) -> Compilation {
        let mut instances=BTreeMap::new();
        for unit in tcx.collect_and_partition_mono_items(()).codegen_units {
            for item in unit.items().keys() {
                if let MonoItem::Fn(instance)=item {
                    instances.insert(identity(tcx,*instance),*instance);
                }
            }
        }
        let env=ty::TypingEnv::fully_monomorphized();
        let mut rows=Vec::new();
        for (id,instance) in instances {
            let body=tcx.instance_mir(instance.def);
            let span=tcx.def_span(instance.def_id());
            let mut calls=Vec::new();
            let mut statements=Vec::new();
            let mut constraints=Vec::new();
            for (block,data) in body.basic_blocks.iter_enumerated() {
                for statement in &data.statements {
                    // Inspection evidence only: these strings never manufacture edges.
                    statements.push(quoted(&format!("{:?}",statement.kind)));
                    if let StatementKind::Assign(assignment)=&statement.kind {
                        let (destination,value)=&**assignment;
                        let dst=place_json(*destination);
                        let (kind,sources)=match value {
                            Rvalue::Use(op)=>("copy",operand_json(tcx,instance,body,op)),
                            Rvalue::Cast(_,op,_)=>{
                                let src=operand_json(tcx,instance,body,op);
                                (if src.starts_with("{\"function\""){"copy"}else{"unsupported_cast"},src)
                            },
                            Rvalue::Ref(_,_,p)=>("reference",format!("{{\"place\":{}}}",place_json(*p))),
                            Rvalue::Aggregate(_,values)=>("aggregate",format!("[{}]",values.iter().map(|o|operand_json(tcx,instance,body,o)).collect::<Vec<_>>().join(","))),
                            _=>("unsupported_rvalue","null".into()),
                        };
                        constraints.push(format!("{{\"kind\":{},\"destination\":{},\"source\":{}}}",quoted(kind),dst,sources));
                    }
                }
                let term=data.terminator();
                match &term.kind {
                    TerminatorKind::Call {func,args,destination,..} => {
                        let function_ty=instance.instantiate_mir_and_normalize_erasing_regions(
                            tcx,env,ty::EarlyBinder::bind(func.ty(&body.local_decls,tcx)));
                        let (status,target)=match *function_ty.kind() {
                            ty::FnDef(def,args)=> match Instance::try_resolve(tcx,env,def,args) {
                                Ok(Some(resolved)) => match resolved.def {
                                    ty::InstanceKind::Virtual(..)=>("unresolved_dyn",None),
                                    _=>("resolved_instance",Some(identity(tcx,resolved))),
                                },
                                _=>("unresolved_instance",None),
                            },
                            ty::FnPtr(..)=>("unresolved_function_pointer",None),
                            _=>("unsupported_callable",None),
                        };
                        calls.push(format!("{{\"block\":{},\"source\":{},\"status\":{},\"target\":{},\"callee_value\":{},\"arguments\":[{}],\"destination\":{}}}",
                            block.index(),quoted(&tcx.sess.source_map().span_to_diagnostic_string(term.source_info.span)),
                            quoted(status),target.as_deref().map(quoted).unwrap_or("null".into()),
                            operand_json(tcx,instance,body,func),args.iter().map(|a|operand_json(tcx,instance,body,&a.node)).collect::<Vec<_>>().join(","),place_json(*destination)));
                    }
                    TerminatorKind::Drop {place,..} => {
                        let drop_ty=instance.instantiate_mir_and_normalize_erasing_regions(
                            tcx,env,ty::EarlyBinder::bind(place.ty(&body.local_decls,tcx).ty));
                        let drop=Instance::resolve_drop_in_place(tcx,drop_ty);
                        calls.push(format!("{{\"block\":{},\"status\":\"drop_instance\",\"target\":{}}}",
                            block.index(),quoted(&identity(tcx,drop))));
                    }
                    _=>{}
                }
            }
            let source_id=format!("{:?}::{}",tcx.def_path_hash(instance.def_id()),tcx.def_path_str(instance.def_id()));
            rows.push(format!("{{\"instance_identity\":{},\"source_identity\":{},\"source\":{},\"phase\":{},\"calls\":[{}],\"constraints\":[{}],\"inspection_statements\":[{}]}}",
                quoted(&id),quoted(&source_id),quoted(&tcx.sess.source_map().span_to_diagnostic_string(span)),
                quoted(&format!("{:?}",body.phase)),calls.join(","),constraints.join(","),statements.join(",")));
        }
        println!("{{\"schema_version\":1,\"accepted_backend\":false,\"instances\":[{}]}}",rows.join(","));
        Compilation::Stop
    }
}

fn main() {
    rustc_driver::run_compiler(&std::env::args().collect::<Vec<_>>(), &mut Probe);
}
