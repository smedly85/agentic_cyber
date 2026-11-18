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
use rustc_middle::mir::UnOp;

use rustc_driver::{Callbacks, Compilation};
use rustc_interface::interface::Compiler;
use rustc_middle::mir::{mono::MonoItem, TerminatorKind, Operand, Place, ProjectionElem, Body, StatementKind, Rvalue, AggregateKind, CastKind, NonDivergingIntrinsic, BinOp};
use rustc_middle::ty::{self, Instance, TyCtxt};
use rustc_middle::ty::adjustment::PointerCoercion;
use std::collections::{BTreeMap, BTreeSet};
use rustc_data_structures::stable_hasher::{HashStable, StableHasher};
use rustc_data_structures::fingerprint::Fingerprint;
use rustc_middle::mir::interpret::{GlobalAlloc, ConstAllocation, Scalar};
use rustc_middle::mir::ConstValue;
use rustc_middle::mir::visit::Visitor;

struct ConstantOperands<'tcx>(Vec<Operand<'tcx>>);
impl<'tcx> Visitor<'tcx> for ConstantOperands<'tcx> {
    fn visit_operand(&mut self,op:&Operand<'tcx>,_:rustc_middle::mir::Location) {
        if matches!(op,Operand::Constant(..)) {self.0.push(op.clone());}
    }
}

// A fat-pointer constant is decoded only with typed reference layout and a
// compiler VTable allocation. No bytes are guessed to be methods or types.
fn dyn_constant<'tcx>(tcx:TyCtxt<'tcx>,instance:Instance<'tcx>,body:&Body<'tcx>,op:&Operand<'tcx>)->Option<(ty::Ty<'tcx>,ty::Ty<'tcx>,ConstAllocation<'tcx>,rustc_abi::Size)> {
    let Operand::Constant(c)=op else {return None};
    let env=ty::TypingEnv::fully_monomorphized();
    let t=instance.instantiate_mir_and_normalize_erasing_regions(tcx,env,ty::EarlyBinder::bind(op.ty(&body.local_decls,tcx)));
    if !matches!(*t.kind(),ty::Ref(..)) || !matches!(*pointee(t).kind(),ty::Dynamic(..)) {return None;}
    let value=instance.instantiate_mir_and_normalize_erasing_regions(tcx,env,ty::EarlyBinder::bind(c.const_)).eval(tcx,env,c.span).ok()?;
    let ConstValue::Indirect{alloc_id,offset}=value else {return None};
    let GlobalAlloc::Memory(allocation)=tcx.global_alloc(alloc_id) else {return None};
    let vtable=allocation.inner().provenance().get_ptr(offset+tcx.data_layout.pointer_size())?;
    let GlobalAlloc::VTable(concrete,_) = tcx.global_alloc(vtable.alloc_id()) else {return None};
    let data=allocation.inner().read_scalar(&tcx, rustc_middle::mir::interpret::alloc_range(offset,tcx.data_layout.pointer_size()),true).ok()?;
    let Scalar::Ptr(pointer,_)=data else {return None};
    let payload=match tcx.global_alloc(pointer.provenance.alloc_id()) {
        GlobalAlloc::Memory(a)=>a,
        GlobalAlloc::Static(def)=>tcx.eval_static_initializer(def).ok()?,
        _=>return None,
    };
    Some((concrete,pointee(t),payload,pointer.prov_and_relative_offset().1))
}

fn constant_fields<'tcx>(tcx:TyCtxt<'tcx>,t:ty::Ty<'tcx>,allocation:ConstAllocation<'tcx>,offset:rustc_abi::Size,path:Vec<String>,depth:usize)->Option<Vec<String>> {
    if depth>12 {return None;}
    let env=ty::TypingEnv::fully_monomorphized();
    let layout=tcx.layout_of(env.as_query_input(t)).ok()?;
    if scalar_storage(tcx,t,0) {return Some(vec![]);}
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
        ty::Array(element,count)=>{
            let count=count.try_to_target_usize(tcx)?;
            let stride=tcx.layout_of(env.as_query_input(element)).ok()?.size;
            let mut values=vec![];
            for i in 0..count {
                let mut sub=path.clone();sub.push(format!("field:{i}"));
                values.extend(constant_fields(tcx,element,allocation,offset+stride*i,sub,depth+1)?);
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

// Structural proof that a value cannot contain a pointer or callable payload.
// In particular, ZST function items and closures are NOT scalar leaves.
fn scalar_storage<'tcx>(tcx:TyCtxt<'tcx>,t:ty::Ty<'tcx>,depth:usize)->bool {
    if depth>16 {return false;}
    let t=tcx.normalize_erasing_regions(ty::TypingEnv::fully_monomorphized(),t);
    match *t.kind() {
        ty::Bool|ty::Char|ty::Int(..)|ty::Uint(..)|ty::Float(..)=>true,
        ty::Adt(def,args) if def.is_struct()=>def.non_enum_variant().fields.iter().all(|f|scalar_storage(tcx,f.ty(tcx,args),depth+1)),
        ty::Adt(def,args) if def.is_enum()=>def.variants().iter().all(|v|v.fields.iter().all(|f|scalar_storage(tcx,f.ty(tcx,args),depth+1))),
        ty::Adt(def,args) if def.is_union()=>def.non_enum_variant().fields.iter().all(|f|scalar_storage(tcx,f.ty(tcx,args),depth+1)),
        ty::Tuple(fields)=>fields.iter().all(|t|scalar_storage(tcx,t,depth+1)),
        ty::Array(t,_)=>scalar_storage(tcx,t,depth+1),
        _=>false,
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
        ProjectionElem::ConstantIndex{offset,from_end:false,..}=>format!("field:{offset}"),
        ProjectionElem::Index(local)=>format!("index:{}",local.index()),
        ProjectionElem::ConstantIndex{..}|ProjectionElem::Subslice{..}=>"unknown_index".into(),
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
    if let Some((concrete,exposed,allocation,offset))=dyn_constant(tcx,instance,body,op) {
        let fields=constant_fields(tcx,concrete,allocation,offset,vec![],0);
        let Operand::Constant(c)=op else {unreachable!()};
        return format!("{{\"constant_reference\":{},\"pointee_key\":{},\"exposed_type_key\":{},\"zero_sized\":false,\"payload_decoded\":{},\"fields\":[{}],\"vtable_concrete_type\":{}}}",
            quoted(&tcx.sess.source_map().span_to_diagnostic_string(c.span)),quoted(&type_key(tcx,concrete)),quoted(&type_key(tcx,exposed)),fields.is_some(),fields.unwrap_or_default().join(","),quoted(&format!("{concrete}")));
    }
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
                if matches!(*inner.kind(),ty::Str) || matches!(*inner.kind(),ty::Slice(element) if scalar_storage(tcx,element,0)) {
                    fields=Some(vec![]);
                }
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
        Operand::Constant(c)=>{
            let evaluated=instance.instantiate_mir_and_normalize_erasing_regions(tcx,env,ty::EarlyBinder::bind(c.const_)).eval(tcx,env,c.span);
            if let Ok(ConstValue::Scalar(Scalar::Ptr(pointer,_)))=evaluated {
                if matches!(*ty.kind(),ty::FnPtr(..)) {
                    if let GlobalAlloc::Function{instance,..}=tcx.global_alloc(pointer.provenance.alloc_id()) {
                        return format!("{{\"function\":{}}}",quoted(&identity(tcx,instance)));
                    }
                }
            }
            if let Ok(ConstValue::Indirect{alloc_id,offset})=evaluated {
                if let GlobalAlloc::Memory(allocation)=tcx.global_alloc(alloc_id) {
                    if let Some(fields)=constant_fields(tcx,ty,allocation,offset,vec![],0) {
                        return format!("{{\"constant_fields\":[{}]}}",fields.join(","));
                    }
                }
            }
            if scalar_storage(tcx,ty,0) || matches!(evaluated,Ok(ConstValue::ZeroSized)) {
                "{\"unmodeled_constant\":true}".into() // No graph payload; preserve baseline serialization.
            } else {
                format!("{{\"unsupported_constant\":{},\"constant_form\":{}}}",quoted(&format!("{ty}")),quoted(&format!("{:?}",c.const_)))
            }
        },
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
        // Discover bodies and unsizings to a fixed point before serializing virtual sites.
        // A dependency helper can introduce a receiver type absent from local mono items.
        loop {
        let previous=(instances.len(),concrete_receivers.len());
        let snapshot=instances.values().copied().collect::<Vec<_>>();
        for instance in &snapshot {
            if matches!(instance.def,ty::InstanceKind::Intrinsic(..)|ty::InstanceKind::Virtual(..)) {continue;}
            if matches!(instance.def,ty::InstanceKind::Item(def) if !tcx.is_mir_available(def)){continue;}
            let body=tcx.instance_mir(instance.def);
            let mut constants=ConstantOperands(vec![]);
            constants.visit_body(body);
            for op in constants.0 {
                if let Some((concrete,exposed,_,_))=dyn_constant(tcx,*instance,body,&op) {
                    if let ty::Dynamic(predicates,..)=*exposed.kind() {
                        if let Some(principal)=predicates.principal() {
                            concrete_receivers.insert((format!("{:?}",tcx.def_path_hash(principal.def_id())),type_key(tcx,concrete)),(principal.def_id(),concrete,principal.skip_binder().args));
                        }
                    }
                }
            }
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
                if let TerminatorKind::Call{func,..}=&data.terminator().kind {
                    let t=instance.instantiate_mir_and_normalize_erasing_regions(tcx,env,ty::EarlyBinder::bind(func.ty(&body.local_decls,tcx)));
                    if let ty::FnDef(def,args)=*t.kind() {
                        if let Ok(Some(target))=Instance::try_resolve(tcx,env,def,args) {
                            if matches!(target.def,ty::InstanceKind::Virtual(..)) {
                                for (_, (trait_id,concrete,trait_args)) in &concrete_receivers {
                                    if tcx.trait_of_assoc(def)!=Some(*trait_id) || !args.iter().skip(1).eq(trait_args.iter()){continue;}
                                    let substitutions=tcx.mk_args_from_iter(args.iter().enumerate().map(|(i,arg)|if i==0{(*concrete).into()}else{arg}));
                                    if let Ok(Some(implementation))=Instance::try_resolve(tcx,env,def,substitutions) {
                                        if !matches!(implementation.def,ty::InstanceKind::Virtual(..)) {instances.insert(identity(tcx,implementation),implementation);}
                                    }
                                }
                            }else{instances.insert(identity(tcx,target),target);}
                        }
                    }
                }
            }
        }
        if previous==(instances.len(),concrete_receivers.len()){break;}
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
                // Compiler-registered intrinsic identities, not source-name matching.
                let contract=tcx.intrinsic(instance.def_id()).and_then(|intrinsic| match intrinsic.name.as_str() {
                    "black_box"=>Some("identity"),
                    "ctpop"=>Some("population_count_scalar"),
                    "assert_inhabited"=>Some("inhabited_type_assertion"),
                    "abort"=>Some("abort_nonreturning"),
                    "caller_location"=>Some("immutable_caller_location"),
                    "size_of_val"|"align_of_val"=>Some("dynamic_layout_scalar"),
                    "saturating_sub"=>Some("saturating_sub_scalar"),
                    "ctlz"|"ctlz_nonzero"=>Some("leading_zero_count_scalar"),
                    "ptr_offset_from_unsigned"=>Some("pointer_distance_scalar"),
                    "cold_path"=>Some("cold_path_leaf"),
                    "select_unpredictable"=>Some("select_value_union"),
                    "arith_offset"=>Some("offset_pointer_union"),
                    "typed_swap_nonoverlapping"=>Some("typed_pointee_swap"),
                    _=>None,
                });
                let reason=match instance.def {
                    ty::InstanceKind::Intrinsic(..)=>"compiler intrinsic: requires explicit semantic model",
                    ty::InstanceKind::Virtual(..)=>"virtual instance: requires receiver resolution",
                    _=>"MIR not encoded",
                };
                let external=tcx.is_foreign_item(instance.def_id()) && !matches!(instance.def,ty::InstanceKind::Intrinsic(..));
                let disposition=if contract.is_some(){"intrinsic_with_contract"}else if external{"legitimate_external_boundary"}else if matches!(instance.def,ty::InstanceKind::Intrinsic(..)){"unsupported_required_body"}else{"missing_required_body"};
                rows.push(format!("{{\"instance_identity\":{},\"body_availability\":{},\"body_classification\":{},\"boundary_reason\":{},\"disposition\":{},\"intrinsic_contract\":{},\"defining_crate\":{},\"def_path\":{},\"source\":{},\"generic\":{},\"compiler_generated\":{},\"calls\":[],\"constraints\":[]}}",
                    quoted(&id),quoted(if contract.is_some(){"intrinsic contract"}else if external {"external body"}else{"missing MIR"}),quoted(if contract.is_some(){"intrinsic_with_contract"}else if external {"external_boundary"}else{"missing_required_body"}),quoted(reason),quoted(disposition),contract.map(quoted).unwrap_or("null".into()),quoted(tcx.crate_name(instance.def_id().krate).as_str()),quoted(&tcx.def_path_str(instance.def_id())),quoted(&tcx.sess.source_map().span_to_diagnostic_string(tcx.def_span(instance.def_id()))),!instance.args.is_empty(),!matches!(instance.def,ty::InstanceKind::Item(..))));
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
                        let cast_evidence=if let Rvalue::Cast(cast,op,to)=value {
                            let from=instance.instantiate_mir_and_normalize_erasing_regions(tcx,env,ty::EarlyBinder::bind(op.ty(&body.local_decls,tcx)));
                            let to=instance.instantiate_mir_and_normalize_erasing_regions(tcx,env,ty::EarlyBinder::bind(*to));
                            format!(",\"cast_evidence\":{{\"cast_kind\":{},\"source_type\":{},\"destination_type\":{}}}",quoted(&format!("{cast:?}")),quoted(&format!("{from}")),quoted(&format!("{to}")))
                        } else {String::new()};
                        let (kind,sources)=match value {
                            Rvalue::Use(op)=>("copy",operand_json(tcx,instance,body,op)),
                            Rvalue::Repeat(op,count)=>{
                                let count=instance.instantiate_mir_and_normalize_erasing_regions(tcx,env,ty::EarlyBinder::bind(*count));
                                if let Some(count)=count.try_to_target_usize(tcx) {
                                    ("repeat_aggregate",format!("{{\"operand\":{},\"count\":{count}}}",operand_json(tcx,instance,body,op)))
                                } else {("unsupported_repeat_count","null".into())}
                            },
                            Rvalue::CopyForDeref(p)=>("copy",format!("{{\"place\":{}}}",place_json(*p))),
                            Rvalue::RawPtr(_,p)=>("reference",format!("{{\"place\":{}}}",place_json(*p))),
                            Rvalue::BinaryOp(BinOp::Offset,ops)=>("pointer_offset",operand_json(tcx,instance,body,&ops.0)),
                            Rvalue::NullaryOp(..)=>("scalar_operation","null".into()),
                            // All remaining BinaryOps return scalar values or scalar/overflow pairs.
                            Rvalue::BinaryOp(..)|Rvalue::Discriminant(..)=>("scalar_operation","null".into()),
                            Rvalue::UnaryOp(UnOp::Not|UnOp::Neg,_) => ("scalar_operation","null".into()),
                            Rvalue::UnaryOp(UnOp::PtrMetadata,op)=>("pointer_metadata",operand_json(tcx,instance,body,op)),
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
                                let preserving=matches!(cast,CastKind::PtrToPtr|CastKind::FnPtrToPtr|
                                    CastKind::PointerCoercion(PointerCoercion::ReifyFnPointer(_)|PointerCoercion::UnsafeFnPointer|
                                        PointerCoercion::MutToConstPointer|PointerCoercion::ArrayToPointer|PointerCoercion::Unsize,_)) ||
                                    (matches!(cast,CastKind::Transmute) && (nonnull || into_nonnull));
                                let pointer_reinterpret=matches!(cast,CastKind::Transmute) && matches!(*from.kind(),ty::RawPtr(..)|ty::Ref(..)) && matches!(*to.kind(),ty::RawPtr(..)|ty::Ref(..));
                                let erases=(matches!(cast,CastKind::PtrToPtr)||pointer_reinterpret) && pointee(from)!=pointee(to);
                                let reinterpret=matches!(cast,CastKind::Transmute) && matches!(*to.kind(),ty::Adt(..)|ty::Tuple(..)|ty::FnPtr(..)|ty::RawPtr(..)|ty::Ref(..)|ty::Array(..));
                                let scalar=|t:ty::Ty<'_>|matches!(*t.kind(),ty::Int(..)|ty::Uint(..)|ty::Float(..)|ty::Bool|ty::Char);
                                let numeric=matches!(cast,CastKind::IntToInt|CastKind::FloatToInt|CastKind::FloatToFloat|CastKind::IntToFloat) || (matches!(cast,CastKind::Transmute) && scalar(from) && scalar(to));
                                let scalar_extract=matches!(cast,CastKind::Transmute) && scalar(to) && scalar_storage(tcx,from,0) &&
                                    tcx.layout_of(env.as_query_input(from)).ok().zip(tcx.layout_of(env.as_query_input(to)).ok()).is_some_and(|(a,b)|a.size==b.size);
                                let address_bits=matches!(cast,CastKind::Transmute) && matches!(*from.kind(),ty::RawPtr(..)|ty::Ref(..)) && matches!(*to.kind(),ty::Uint(ty::UintTy::Usize));
                                let pointer_reconstruction=matches!(cast,CastKind::Transmute) && scalar(from) && matches!(*to.kind(),ty::RawPtr(..)|ty::Ref(..)|ty::FnPtr(..));
                                let provenance_free=matches!(cast,CastKind::Transmute) && matches!(*from.kind(),ty::Uint(ty::UintTy::Usize)) && matches!(*to.kind(),ty::RawPtr(..));
                                if matches!(cast,CastKind::PointerCoercion(PointerCoercion::ClosureFnPointer(_),_)) {
                                    if let ty::Closure(def,args)=*from.kind() {
                                        let target=Instance::resolve_closure(tcx,def,args,ty::ClosureKind::FnOnce);
                                        if transitive {instances.insert(identity(tcx,target),target);}
                                        ("copy",format!("{{\"function\":{}}}",quoted(&identity(tcx,target))))
                                    } else {("unsupported_cast",src)}
                                }
                                else if address_bits {("pointer_address_bits",src)}
                                else if scalar_extract && !numeric {("pointer_free_scalar_extract",src)}
                                else if provenance_free {("provenance_free_pointer",src)}
                                else if pointer_reconstruction {("unsupported_pointer_reconstruction",src)}
                                else if erases {("pointer_cast",format!("{{\"operand\":{},\"pointee_key\":{}}}",src,quoted(&type_key(tcx,pointee(to)))))}
                                else {(if numeric {"scalar_operation"}else if preserving || pointer_reinterpret || matches!(cast,CastKind::Subtype) {"copy"}else if reinterpret {"reinterpret"}else{"unsupported_cast"},src)}
                            },
                            Rvalue::Ref(_,_,p)=>("reference",format!("{{\"place\":{}}}",place_json(*p))),
                            Rvalue::Aggregate(kind,values)=>{
                                if matches!(&**kind,AggregateKind::RawPtr(..)) {
                                    ("raw_pointer_aggregate",format!("[{}]",values.iter().map(|o|operand_json(tcx,instance,body,o)).collect::<Vec<_>>().join(",")))
                                }else if matches!(&**kind,AggregateKind::Adt(def,..) if tcx.adt_def(*def).is_union()) {
                                    ("union_aggregate",format!("[{}]",values.iter().map(|o|operand_json(tcx,instance,body,o)).collect::<Vec<_>>().join(",")))
                                } else {
                                let prefix=match &**kind {
                                    AggregateKind::Adt(def,variant,..) if tcx.adt_def(*def).is_enum()=>Some(format!("[\"variant:{}\"]",variant.index())),
                                    AggregateKind::Adt(def,..) if tcx.adt_def(*def).is_struct()=>Some("[]".into()),
                                    AggregateKind::Tuple|AggregateKind::Closure(..)|AggregateKind::Array(..)=>Some("[]".into()),
                                    _=>None,
                                };
                                if let Some(prefix)=prefix {
                                    ("typed_aggregate",format!("{{\"prefix\":{},\"fields\":[{}]}}",prefix,values.iter().map(|o|operand_json(tcx,instance,body,o)).collect::<Vec<_>>().join(",")))
                                } else { ("unsupported_aggregate","null".into()) }
                                }
                            },
                            _=>("unsupported_rvalue","null".into()),
                        };
                        constraints.push(format!("{{\"kind\":{},\"destination\":{},\"source\":{},\"union_write\":{},\"source_span\":{},\"operation_detail\":{}{}}}",quoted(kind),dst,sources,
                            union_access(tcx,body,*destination),quoted(&tcx.sess.source_map().span_to_diagnostic_string(statement.source_info.span)),quoted(&format!("{:?}",value)),cast_evidence));
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
                            if tcx.lang_items().exchange_malloc_fn()==Some(def) && tcx.is_diagnostic_item(rustc_span::Symbol::intern("box_new"),instance.def_id()) {
                                let allocated=instance.args.type_at(0);
                                semantic=format!("{{\"kind\":\"box_storage_allocation\",\"allocated_type\":{},\"type_key\":{},\"pointer_paths\":[],\"source_def_path\":{}}}",
                                    quoted(&format!("{allocated}")),quoted(&type_key(tcx,allocated)),quoted(&format!("{:?}",tcx.def_path_hash(instance.def_id()))));
                            }
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
            // Prove a MIR index local has one constant value across all writes.
            // Escaping its address or writing it via a call invalidates the proof.
            let mut indices:BTreeMap<usize,Option<u64>>=BTreeMap::new();
            for i in 0..=body.arg_count {indices.insert(i,None);}
            for data in body.basic_blocks.iter() {
                for statement in &data.statements {
                    if let StatementKind::Assign(assignment)=&statement.kind {
                        let (dst,rv)=&**assignment;
                        if dst.projection.is_empty() {
                            let value=if let Rvalue::Use(Operand::Constant(c))=rv {
                                let cty=instance.instantiate_mir_and_normalize_erasing_regions(tcx,env,ty::EarlyBinder::bind(c.const_.ty()));
                                if cty==tcx.types.usize {instance.instantiate_mir_and_normalize_erasing_regions(tcx,env,ty::EarlyBinder::bind(c.const_)).eval(tcx,env,c.span).ok().and_then(|v|v.try_to_target_usize(tcx))} else {None}
                            } else {None};
                            indices.entry(dst.local.index()).and_modify(|old|if *old!=value {*old=None}).or_insert(value);
                        }
                        if let Rvalue::Ref(_,_,p)|Rvalue::RawPtr(_,p)=rv {indices.insert(p.local.index(),None);}
                    }
                }
                if let TerminatorKind::Call{destination,..}=&data.terminator().kind {indices.insert(destination.local.index(),None);}
            }
            for i in 0..body.local_decls.len() {
                let from=quoted(&format!("index:{i}"));
                let to=quoted(&indices.get(&i).copied().flatten().map(|n|format!("field:{n}")).unwrap_or("unknown_index".into()));
                for text in constraints.iter_mut().chain(calls.iter_mut()) {*text=text.replace(&from,&to);}
            }
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
            let kind=match instance.def {
                ty::InstanceKind::Item(..)=>"item",
                ty::InstanceKind::DropGlue(..)=>"drop_glue",
                ty::InstanceKind::ClosureOnceShim{..}=>"closure_once_shim",
                ty::InstanceKind::FnPtrShim(..)=>"fn_pointer_shim",
                ty::InstanceKind::ReifyShim(..)=>"reify_shim",
                ty::InstanceKind::VTableShim(..)=>"vtable_shim",
                _=>"compiler_shim",
            };
            rows.push(format!("{{\"instance_identity\":{},\"source_identity\":{},\"source\":{},\"phase\":{},\"calls\":[{}],\"constraints\":[{}],\"inspection_statements\":[{}],\"body_availability\":{},\"local_definition\":{},\"defining_crate\":{},\"inlined_scopes\":{},\"instance_kind\":{},\"local_types\":[{}],\"closure_body\":{},\"argument_count\":{},\"body_classification\":{},\"disposition\":\"body_available\",\"def_path\":{},\"generic\":{},\"compiler_generated\":{},\"symbol\":{}}}",
                quoted(&id),quoted(&source_id),quoted(&tcx.sess.source_map().span_to_diagnostic_string(span)),
                quoted(&format!("{:?}",body.phase)),calls.join(","),constraints.join(","),statements.join(","),
                quoted(availability),instance.def_id().is_local(),quoted(tcx.crate_name(instance.def_id().krate).as_str()),inlined_scopes,
                quoted(kind),locals.join(","),
                matches!(instance.def,ty::InstanceKind::Item(def) if tcx.is_closure_like(def)),body.arg_count,quoted(classification),quoted(&tcx.def_path_str(instance.def_id())),!instance.args.is_empty(),kind!="item",quoted(tcx.symbol_name(instance).name)));
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
