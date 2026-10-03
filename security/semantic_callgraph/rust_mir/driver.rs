//! Controlled API/stage probe. Not an accepted may-call backend.
#![feature(rustc_private)]
extern crate rustc_driver;
extern crate rustc_interface;
extern crate rustc_middle;
extern crate rustc_hir;
extern crate rustc_span;
extern crate rustc_target;
extern crate rustc_data_structures;
extern crate rustc_abi;

use rustc_driver::{Callbacks, Compilation};
use rustc_interface::interface::Compiler;
use rustc_middle::mir::{mono::MonoItem, TerminatorKind, Operand, Place, ProjectionElem, Body, StatementKind, Rvalue, AggregateKind, CastKind, NonDivergingIntrinsic, BinOp};
use rustc_middle::ty::{self, Instance, TyCtxt};
use std::collections::{BTreeMap, BTreeSet};
use rustc_data_structures::stable_hasher::{HashStable, StableHasher};
use rustc_data_structures::fingerprint::Fingerprint;
use rustc_middle::mir::interpret::{GlobalAlloc, ConstAllocation, Scalar};

fn constant_fields<'tcx>(tcx:TyCtxt<'tcx>,t:ty::Ty<'tcx>,allocation:ConstAllocation<'tcx>,offset:rustc_abi::Size,path:Vec<String>,depth:usize)->Option<Vec<String>> {
    if depth>12 {return None;}
    let env=ty::TypingEnv::fully_monomorphized();
    let layout=tcx.layout_of(env.as_query_input(t)).ok()?;
    match *t.kind() {
        ty::FnPtr(..)=>{
            let provenance=allocation.inner().provenance().get_ptr(offset)?;
            if let GlobalAlloc::Function{instance,..}=tcx.global_alloc(provenance.alloc_id()) {
                Some(vec![format!("{{\"path\":[{}],\"function\":{}}}",path.iter().map(|p|quoted(p)).collect::<Vec<_>>().join(","),quoted(&identity(tcx,instance)))])
            } else {None}
        },
        ty::Adt(def,args) if !def.is_enum() && !def.is_union()=>{
            let mut values=vec![];
            for (i,field) in def.non_enum_variant().fields.iter_enumerated() {
                let mut sub=path.clone();sub.push(format!("field:{}",i.index()));
                values.extend(constant_fields(tcx,field.ty(tcx,args),allocation,offset+layout.fields.offset(i.index()),sub,depth+1)?);
            }
            Some(values)
        },
        ty::Tuple(fields)=>{
            let mut values=vec![];
            for (i,field) in fields.iter().enumerate() {
                let mut sub=path.clone();sub.push(format!("field:{i}"));
                values.extend(constant_fields(tcx,field,allocation,offset+layout.fields.offset(i),sub,depth+1)?);
            }
            Some(values)
        },
        ty::Bool|ty::Char|ty::Int(..)|ty::Uint(..)|ty::Float(..)=>Some(vec![]),
        _ if layout.size.bytes()==0=>Some(vec![]),
        _=>None,
    }
}

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

fn type_key<'tcx>(tcx:TyCtxt<'tcx>, t:ty::Ty<'tcx>)->String {
    let hash:Fingerprint=tcx.with_stable_hashing_context(|mut context| {
        let mut hasher=StableHasher::new(); t.hash_stable(&mut context,&mut hasher); hasher.finish()
    });
    format!("{hash:?}")
}

fn pointee<'tcx>(t:ty::Ty<'tcx>)->ty::Ty<'tcx> {
    match *t.kind() {
        ty::Ref(_,inner,_)|ty::RawPtr(inner,_)=>inner,
        ty::Adt(def,args) if def.is_box()=>args.type_at(0),
        _=>t,
    }
}

// Enumerate the actual typed Box representation, stopping at its raw pointer.
// This models ownership representation, never fields of the pointee object.
fn box_pointer_paths<'tcx>(tcx:TyCtxt<'tcx>, t:ty::Ty<'tcx>, prefix:Vec<String>, depth:usize)->Vec<Vec<String>> {
    if depth>8 { return vec![]; }
    match *t.kind() {
        ty::RawPtr(..)=>vec![prefix],
        ty::Adt(def,args) if !def.is_enum() && !def.is_union()=>{
            let mut result=vec![];
            for (i,field) in def.non_enum_variant().fields.iter_enumerated() {
                let mut path=prefix.clone();path.push(format!("field:{}",i.index()));
                result.extend(box_pointer_paths(tcx,field.ty(tcx,args),path,depth+1));
            }
            result
        },
        _=>vec![],
    }
}

fn place_json(place: Place<'_>) -> String {
    let projections:Vec<String>=place.projection.iter().map(|p|quoted(&match p {
        ProjectionElem::Deref=>"deref".into(),
        ProjectionElem::Field(i,_)=>format!("field:{}",i.index()),
        ProjectionElem::Downcast(_,i)=>format!("variant:{}",i.index()),
        ProjectionElem::Index(_)|ProjectionElem::ConstantIndex{..}|ProjectionElem::Subslice{..}=>"unknown_index".into(),
        _=>"unsupported_projection".into(),
    })).collect();
    format!("[{},[{}]]",place.local.index(),projections.join(","))
}

fn union_access<'tcx>(tcx:TyCtxt<'tcx>,body:&Body<'tcx>,place:Place<'tcx>)->bool {
    place.iter_projections().any(|(base,projection)|matches!(projection,ProjectionElem::Field(..)) &&
        matches!(*base.ty(&body.local_decls,tcx).ty.kind(),ty::Adt(def,_) if def.is_union()))
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
        Operand::Copy(p)|Operand::Move(p)=>format!("{{\"place\":{},\"union_read\":{}}}",place_json(*p),union_access(tcx,body,*p)),
        Operand::Constant(c) if matches!(*ty.kind(),ty::Ref(..))=>{
            let inner=pointee(ty);
            let zero=tcx.layout_of(env.as_query_input(inner)).is_ok_and(|layout|layout.size.bytes()==0);
            let evaluated=instance.instantiate_mir_and_normalize_erasing_regions(tcx,env,ty::EarlyBinder::bind(c.const_)).eval(tcx,env,c.span);
            let mut fields=None;
            let mut source=tcx.sess.source_map().span_to_diagnostic_string(c.span);
            if let Ok(value)=evaluated {
                if let Some(Scalar::Ptr(pointer,_))=value.try_to_scalar() {
                    let allocation=match tcx.global_alloc(pointer.provenance.alloc_id()) {
                        GlobalAlloc::Memory(a)=>Some(a),
                        GlobalAlloc::Static(def)=>{
                            source=format!("static:{:?}",tcx.def_path_hash(def));
                            tcx.eval_static_initializer(def).ok()
                        },
                        _=>None,
                    };
                    if let Some(allocation)=allocation {fields=constant_fields(tcx,inner,allocation,pointer.prov_and_relative_offset().1,vec![],0);}
                }
            }
            format!("{{\"constant_reference\":{},\"pointee_key\":{},\"zero_sized\":{},\"payload_decoded\":{},\"fields\":[{}]}}",
                    quoted(&source),quoted(&type_key(tcx,inner)),zero,fields.is_some()||zero,fields.unwrap_or_default().join(","))
        },
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
        // Candidate resolution is driven by compiler-observed unsizing casts.
        // The solver will select only candidates whose receiver objects flow in.
        let mut concrete_receivers=BTreeMap::new();
        for instance in instances.values() {
            let body=tcx.instance_mir(instance.def);
            for data in body.basic_blocks.iter() {
                for statement in &data.statements {
                    if let StatementKind::Assign(assignment)=&statement.kind {
                        if let Rvalue::Cast(_,op,dest)=&assignment.1 {
                            let from=instance.instantiate_mir_and_normalize_erasing_regions(tcx,env,ty::EarlyBinder::bind(op.ty(&body.local_decls,tcx)));
                            let to=instance.instantiate_mir_and_normalize_erasing_regions(tcx,env,ty::EarlyBinder::bind(*dest));
                            let concrete=pointee(from);
                            if let ty::Dynamic(predicates,..)=*pointee(to).kind() {
                                if let Some(principal)=predicates.principal() {
                                    if !matches!(*concrete.kind(),ty::Dynamic(..)) {
                                        concrete_receivers.insert((format!("{:?}",tcx.def_path_hash(principal.def_id())),type_key(tcx,concrete)),(principal.def_id(),concrete,principal.skip_binder().args));
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        let mut rows=Vec::new();
        let transitive=std::env::var_os("MIR_PROBE_TRANSITIVE").is_some();
        let mut visited=BTreeSet::new();
        while let Some((id,instance))=instances.pop_first() {
            if !visited.insert(id.clone()) { continue; }
            let available=match instance.def {
                ty::InstanceKind::Item(def)=>tcx.is_mir_available(def),
                ty::InstanceKind::Intrinsic(..)|ty::InstanceKind::Virtual(..)=>false,
                _=>true,
            };
            if !available {
                let reason=match instance.def {
                    ty::InstanceKind::Intrinsic(..)=>"compiler intrinsic: requires explicit semantic model",
                    ty::InstanceKind::Virtual(..)=>"virtual instance: requires receiver resolution",
                    _=>"MIR not encoded",
                };
                let external=tcx.is_foreign_item(instance.def_id()) && !matches!(instance.def,ty::InstanceKind::Intrinsic(..));
                rows.push(format!("{{\"instance_identity\":{},\"body_availability\":{},\"body_classification\":{},\"boundary_reason\":{},\"calls\":[],\"constraints\":[]}}",
                    quoted(&id),quoted(if external {"external body"}else{"missing MIR"}),quoted(if external {"external_boundary"}else{"missing_required_body"}),quoted(reason)));
                continue;
            }
            let body=tcx.instance_mir(instance.def);
            let span=tcx.def_span(instance.def_id());
            let mut calls=Vec::new();
            let mut statements=Vec::new();
            let mut constraints=Vec::new();
            for (block,data) in body.basic_blocks.iter_enumerated() {
                for statement in &data.statements {
                    // Inspection evidence only: these strings never manufacture edges.
                    statements.push(quoted(&format!("{:?}",statement.kind)));
                    if let StatementKind::Intrinsic(intrinsic)=&statement.kind {
                        if let NonDivergingIntrinsic::CopyNonOverlapping(copy)=&**intrinsic {
                            constraints.push(format!("{{\"kind\":\"byte_copy\",\"destination\":null,\"source\":[{},{}],\"source_span\":{}}}",
                                operand_json(tcx,instance,body,&copy.src),operand_json(tcx,instance,body,&copy.dst),
                                quoted(&tcx.sess.source_map().span_to_diagnostic_string(statement.source_info.span))));
                        }
                    }
                    if let StatementKind::Assign(assignment)=&statement.kind {
                        let (destination,value)=&**assignment;
                        let dst=place_json(*destination);
                        let (kind,sources)=match value {
                            Rvalue::Use(op)=>("copy",operand_json(tcx,instance,body,op)),
                            Rvalue::CopyForDeref(p)=>("copy",format!("{{\"place\":{}}}",place_json(*p))),
                            Rvalue::RawPtr(_,p)=>("reference",format!("{{\"place\":{}}}",place_json(*p))),
                            Rvalue::BinaryOp(BinOp::Offset,ops)=>("pointer_offset",operand_json(tcx,instance,body,&ops.0)),
                            Rvalue::Cast(cast,op,to)=>{
                                let src=operand_json(tcx,instance,body,op);
                                let from=instance.instantiate_mir_and_normalize_erasing_regions(tcx,env,ty::EarlyBinder::bind(op.ty(&body.local_decls,tcx)));
                                let to=instance.instantiate_mir_and_normalize_erasing_regions(tcx,env,ty::EarlyBinder::bind(*to));
                                let nonnull=match *from.kind() {
                                    ty::Adt(def,params)=>tcx.is_diagnostic_item(rustc_span::Symbol::intern("NonNull"),def.did()) &&
                                        matches!(*to.kind(),ty::RawPtr(p,_) if p==params.type_at(0)),
                                    _=>false,
                                };
                                let into_nonnull=match *to.kind() {
                                    ty::Adt(def,params)=>tcx.is_diagnostic_item(rustc_span::Symbol::intern("NonNull"),def.did()) &&
                                        matches!(*from.kind(),ty::RawPtr(p,_) if p==params.type_at(0)),
                                    _=>false,
                                };
                                let preserving=matches!(cast,CastKind::PtrToPtr|CastKind::PointerCoercion(..)) || nonnull || into_nonnull;
                                let erases=matches!(cast,CastKind::PtrToPtr) && pointee(from)!=pointee(to);
                                let reinterpret=matches!(cast,CastKind::Transmute) && matches!(*to.kind(),ty::Adt(..)|ty::Tuple(..)|ty::FnPtr(..)|ty::RawPtr(..));
                                (if erases {"pointer_cast"}else if src.starts_with("{\"function\"") || preserving {"copy"}else if reinterpret {"reinterpret"}else{"unsupported_cast"},src)
                            },
                            Rvalue::Ref(_,_,p)=>("reference",format!("{{\"place\":{}}}",place_json(*p))),
                            Rvalue::Aggregate(kind,values)=>{
                                if matches!(&**kind,AggregateKind::Adt(def,..) if tcx.adt_def(*def).is_union()) {
                                    ("union_aggregate",format!("[{}]",values.iter().map(|o|operand_json(tcx,instance,body,o)).collect::<Vec<_>>().join(",")))
                                } else {
                                let prefix=match &**kind {
                                    AggregateKind::Adt(def,variant,..) if tcx.adt_def(*def).is_enum()=>Some(format!("[\"variant:{}\"]",variant.index())),
                                    AggregateKind::Adt(def,..) if tcx.adt_def(*def).is_struct()=>Some("[]".into()),
                                    AggregateKind::Tuple|AggregateKind::Closure(..)=>Some("[]".into()),
                                    _=>None,
                                };
                                if let Some(prefix)=prefix {
                                    ("typed_aggregate",format!("{{\"prefix\":{},\"fields\":[{}]}}",prefix,values.iter().map(|o|operand_json(tcx,instance,body,o)).collect::<Vec<_>>().join(",")))
                                } else { ("unsupported_aggregate","null".into()) }
                                }
                            },
                            _=>("unsupported_rvalue","null".into()),
                        };
                        constraints.push(format!("{{\"kind\":{},\"destination\":{},\"source\":{},\"union_write\":{},\"source_span\":{}}}",quoted(kind),dst,sources,
                            union_access(tcx,body,*destination),quoted(&tcx.sess.source_map().span_to_diagnostic_string(statement.source_info.span))));
                    }
                }
                let term=data.terminator();
                match &term.kind {
                    TerminatorKind::Call {func,args,destination,..} => {
                        let function_ty=instance.instantiate_mir_and_normalize_erasing_regions(
                            tcx,env,ty::EarlyBinder::bind(func.ty(&body.local_decls,tcx)));
                        let mut dyn_candidates=vec![];
                        let mut trait_method="null".to_string();
                        let (status,target)=match *function_ty.kind() {
                            ty::FnDef(def,args)=> match Instance::try_resolve(tcx,env,def,args) {
                                Ok(Some(resolved)) => match resolved.def {
                                    ty::InstanceKind::Virtual(..)=>{
                                        trait_method=quoted(&format!("{:?}",tcx.def_path_hash(def)));
                                        for ((_,key),(trait_id,concrete,trait_args)) in &concrete_receivers {
                                            if tcx.trait_of_assoc(def)!=Some(*trait_id) {continue;}
                                            if !args.iter().skip(1).eq(trait_args.iter()) {continue;}
                                            let substitutions=tcx.mk_args_from_iter(args.iter().enumerate().map(|(index,arg)| if index==0 {(*concrete).into()} else {arg}));
                                            if let Ok(Some(target))=Instance::try_resolve(tcx,env,def,substitutions) {
                                                if matches!(target.def,ty::InstanceKind::Virtual(..)) {continue;}
                                                let target_id=identity(tcx,target);
                                                dyn_candidates.push(format!("{{\"type_key\":{},\"receiver_type\":{},\"target\":{}}}",quoted(key),quoted(&format!("{concrete}")),quoted(&target_id)));
                                                if transitive {instances.insert(target_id,target);}
                                            }
                                        }
                                        ("unresolved_dyn",None)
                                    },
                                    _=>{
                                        let target_id=identity(tcx,resolved);
                                        if transitive && !visited.contains(&target_id) { instances.insert(target_id.clone(),resolved); }
                                        ("resolved_instance",Some(target_id))
                                    },
                                },
                                _=>("unresolved_instance",None),
                            },
                            ty::FnPtr(..)=>("unresolved_function_pointer",None),
                            _=>("unsupported_callable",None),
                        };
                        let mut semantic="null".to_string();
                        let rust_call=match *function_ty.kind() {
                            ty::FnDef(def,params) if !tcx.is_closure_like(def)=>tcx.fn_sig(def).instantiate(tcx,params).skip_binder().abi==rustc_abi::ExternAbi::RustCall,
                            _=>false,
                        };
                        if let ty::FnDef(def,params)=*function_ty.kind() {
                            if tcx.is_diagnostic_item(rustc_span::Symbol::intern("box_new"),def) {
                                let allocated=params.type_at(0);
                                let dest_ty=instance.instantiate_mir_and_normalize_erasing_regions(tcx,env,ty::EarlyBinder::bind(destination.ty(&body.local_decls,tcx).ty));
                                let paths=box_pointer_paths(tcx,dest_ty,vec![],0);
                                semantic=format!("{{\"kind\":\"box_new\",\"allocated_type\":{},\"type_key\":{},\"pointer_paths\":[{}],\"source_def_path\":{}}}",
                                    quoted(&format!("{allocated}")),quoted(&type_key(tcx,allocated)),
                                    paths.iter().map(|p|format!("[{}]",p.iter().map(|v|quoted(v)).collect::<Vec<_>>().join(","))).collect::<Vec<_>>().join(","),
                                    quoted(&format!("{:?}",tcx.def_path_hash(instance.def_id()))));
                            }
                        }
                        calls.push(format!("{{\"block\":{},\"source\":{},\"status\":{},\"target\":{},\"callee_value\":{},\"arguments\":[{}],\"destination\":{},\"semantic_operation\":{},\"trait_method\":{},\"dyn_candidates\":[{}],\"rust_call\":{}}}",
                            block.index(),quoted(&tcx.sess.source_map().span_to_diagnostic_string(term.source_info.span)),
                            quoted(status),target.as_deref().map(quoted).unwrap_or("null".into()),
                            operand_json(tcx,instance,body,func),args.iter().map(|a|operand_json(tcx,instance,body,&a.node)).collect::<Vec<_>>().join(","),place_json(*destination),semantic,trait_method,dyn_candidates.join(","),rust_call));
                    }
                    TerminatorKind::Drop {place,..} => {
                        let drop_ty=instance.instantiate_mir_and_normalize_erasing_regions(
                            tcx,env,ty::EarlyBinder::bind(place.ty(&body.local_decls,tcx).ty));
                        let drop=Instance::resolve_drop_in_place(tcx,drop_ty);
                        if transitive { instances.insert(identity(tcx,drop),drop); }
                        calls.push(format!("{{\"block\":{},\"status\":\"drop_instance\",\"target\":{},\"arguments\":[{{\"reference\":{}}}],\"destination\":null}}",
                            block.index(),quoted(&identity(tcx,drop)),place_json(*place)));
                    }
                    _=>{}
                }
            }
            let source_id=format!("{:?}::{}",tcx.def_path_hash(instance.def_id()),tcx.def_path_str(instance.def_id()));
            let inlined_scopes=body.source_scopes.iter().filter(|scope|scope.inlined.is_some()).count();
            let availability=if !instance.args.is_empty() { "generic instantiated body" } else { "available body" };
            let crate_name=tcx.crate_name(instance.def_id().krate);
            let classification=if instance.def_id().is_local() {"local_body_available"}
                else if matches!(crate_name.as_str(),"core"|"alloc"|"std") {
                    if instance.args.is_empty() {"std_nongeneric_body_available"}else{"std_generic_body_available"}
                }else{"dependency_body_available"};
            let locals=body.local_decls.iter().map(|decl| {
                let t=instance.instantiate_mir_and_normalize_erasing_regions(tcx,env,ty::EarlyBinder::bind(decl.ty));
                quoted(&type_key(tcx,t))
            }).collect::<Vec<_>>();
            rows.push(format!("{{\"instance_identity\":{},\"source_identity\":{},\"source\":{},\"phase\":{},\"calls\":[{}],\"constraints\":[{}],\"inspection_statements\":[{}],\"body_availability\":{},\"local_definition\":{},\"defining_crate\":{},\"inlined_scopes\":{},\"instance_kind\":{},\"local_types\":[{}],\"closure_body\":{},\"argument_count\":{},\"body_classification\":{}}}",
                quoted(&id),quoted(&source_id),quoted(&tcx.sess.source_map().span_to_diagnostic_string(span)),
                quoted(&format!("{:?}",body.phase)),calls.join(","),constraints.join(","),statements.join(","),
                quoted(availability),instance.def_id().is_local(),quoted(tcx.crate_name(instance.def_id().krate).as_str()),inlined_scopes,
                quoted(&format!("{:?}",std::mem::discriminant(&instance.def))),locals.join(","),
                matches!(instance.def,ty::InstanceKind::Item(def) if tcx.is_closure_like(def)),body.arg_count,quoted(classification)));
        }
        rows.sort();
        let document=format!("{{\"schema_version\":1,\"accepted_backend\":false,\"instances\":[{}]}}",rows.join(","));
        if let Some(path)=std::env::var_os("MIR_PROBE_OUTPUT") {
            std::fs::write(path,document+"\n").expect("write controlled MIR evidence");
        } else { println!("{document}"); }
        if std::env::var_os("MIR_PROBE_CONTINUE").is_some() { Compilation::Continue } else { Compilation::Stop }
    }
}

fn main() {
    rustc_driver::run_compiler(&std::env::args().collect::<Vec<_>>(), &mut Probe);
}
