// agent-rs-items: compiler-based inventory of local Rust items (rustc 1.93).
//
// Prints one JSON document (to $AGENT_RS_ITEMS_OUT or stdout) listing every
// local fn/method with its exact source span, body span and the compiler's
// view of its signature, plus every other local item (for classifying what
// an agent added). Usable as `rs-items <rustc args>` or as
// RUSTC_WORKSPACE_WRAPPER (then argv[1] is the real rustc and is skipped).
#![feature(rustc_private)]
extern crate rustc_driver;
extern crate rustc_hir;
extern crate rustc_interface;
extern crate rustc_middle;
extern crate rustc_span;

use rustc_driver::{Callbacks, Compilation};
use rustc_hir::def::DefKind;
use rustc_interface::interface::Compiler;
use rustc_middle::ty::TyCtxt;
use rustc_span::Span;
use std::io::Write;

struct Items;

fn quoted(s: &str) -> String {
    let mut out = String::with_capacity(s.len() + 2);
    out.push('"');
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if (c as u32) < 0x20 => out.push_str(&format!("\\u{:04x}", c as u32)),
            c => out.push(c),
        }
    }
    out.push('"');
    out
}

fn place(tcx: TyCtxt<'_>, span: Span) -> (String, usize, usize) {
    let sm = tcx.sess.source_map();
    let diag = sm.span_to_diagnostic_string(span);
    // "path:line:col: line:col" -> path
    let mut parts: Vec<&str> = diag.rsplitn(5, ':').collect();
    let file = if parts.len() == 5 { parts.pop().unwrap().to_string() } else { diag.clone() };
    let lo = sm.lookup_byte_offset(span.lo()).pos.0 as usize;
    let hi = sm.lookup_byte_offset(span.hi()).pos.0 as usize;
    (file, lo, hi)
}

fn kind_name(kind: DefKind) -> &'static str {
    match kind {
        DefKind::Fn => "fn",
        DefKind::AssocFn => "assoc_fn",
        DefKind::Struct => "struct",
        DefKind::Enum => "enum",
        DefKind::Union => "union",
        DefKind::TyAlias => "type",
        DefKind::Const => "const",
        DefKind::Static { .. } => "static",
        DefKind::Trait => "trait",
        DefKind::Use => "use",
        DefKind::Impl { .. } => "impl",
        DefKind::Macro(_) => "macro",
        DefKind::Mod => "mod",
        DefKind::AssocConst => "assoc_const",
        DefKind::AssocTy => "assoc_type",
        _ => "other",
    }
}

impl Callbacks for Items {
    fn after_analysis<'tcx>(&mut self, _: &Compiler, tcx: TyCtxt<'tcx>) -> Compilation {
        let mut fns = Vec::new();
        let mut others = Vec::new();
        for def_id in tcx.hir_crate_items(()).definitions() {
            let kind = tcx.def_kind(def_id);
            let span = tcx.source_span(def_id);
            if span.from_expansion() && !matches!(kind, DefKind::Fn | DefKind::AssocFn) {
                continue;
            }
            let (file, lo, hi) = place(tcx, span);
            let path = tcx.def_path_str(def_id.to_def_id());
            let verbose = tcx.def_path(def_id.to_def_id()).to_string_no_crate_verbose();
            match kind {
                DefKind::Fn | DefKind::AssocFn => {
                    let parent = tcx.opt_parent(def_id.to_def_id());
                    let parent_kind = match parent.map(|p| tcx.def_kind(p)) {
                        Some(DefKind::Impl { of_trait: true }) => "trait_impl",
                        Some(DefKind::Impl { of_trait: false }) => "inherent_impl",
                        Some(DefKind::Trait) => "trait",
                        _ => "module",
                    };
                    let parent_span = match parent {
                        Some(p) if parent_kind != "module" => {
                            let (_, plo, phi) = place(tcx, tcx.source_span(p.expect_local()));
                            format!("[{},{}]", plo, phi)
                        }
                        _ => "null".to_string(),
                    };
                    let has_body = tcx.hir_maybe_body_owned_by(def_id).is_some();
                    let (body_lo, params) = match tcx.hir_maybe_body_owned_by(def_id) {
                        Some(body) => {
                            let (_, blo, _) = place(tcx, body.value.span);
                            let sm = tcx.sess.source_map();
                            let names: Vec<String> = body
                                .params
                                .iter()
                                .map(|p| quoted(&sm.span_to_snippet(p.pat.span).unwrap_or_default()))
                                .collect();
                            (blo.to_string(), names.join(","))
                        }
                        None => ("null".to_string(), String::new()),
                    };
                    let sig = tcx.fn_sig(def_id).instantiate_identity();
                    let preds: Vec<String> = tcx
                        .predicates_of(def_id)
                        .predicates
                        .iter()
                        .map(|(clause, _)| quoted(&format!("{}", clause)))
                        .collect();
                    let generics: Vec<String> = tcx
                        .generics_of(def_id)
                        .own_params
                        .iter()
                        .map(|p| quoted(p.name.as_str()))
                        .collect();
                    fns.push(format!(
                        "{{\"path\":{},\"verbose\":{},\"kind\":{},\"parent_kind\":{},\"parent_span\":{},\"file\":{},\"lo\":{},\"hi\":{},\"body_lo\":{},\"has_body\":{},\"from_expansion\":{},\"fn_sig\":{},\"predicates\":[{}],\"generics\":[{}],\"param_patterns\":[{}],\"visibility\":{},\"asyncness\":{}}}",
                        quoted(&path), quoted(&verbose), quoted(kind_name(kind)), quoted(parent_kind), parent_span,
                        quoted(&file), lo, hi, body_lo, has_body, span.from_expansion(),
                        quoted(&format!("{}", sig)), preds.join(","), generics.join(","), params,
                        quoted(&format!("{:?}", tcx.visibility(def_id))), quoted(&format!("{:?}", tcx.asyncness(def_id)))
                    ));
                }
                DefKind::Closure | DefKind::SyntheticCoroutineBody | DefKind::LifetimeParam | DefKind::TyParam
                | DefKind::ConstParam | DefKind::Field | DefKind::Variant | DefKind::Ctor(..)
                | DefKind::AnonConst | DefKind::InlineConst | DefKind::OpaqueTy => {}
                _ => others.push(format!(
                    "{{\"path\":{},\"verbose\":{},\"kind\":{},\"file\":{},\"lo\":{},\"hi\":{}}}",
                    quoted(&path), quoted(&verbose), quoted(kind_name(kind)), quoted(&file), lo, hi
                )),
            }
        }
        let doc = format!(
            "{{\"crate\":{},\"functions\":[{}],\"items\":[{}]}}\n",
            quoted(tcx.crate_name(rustc_span::def_id::LOCAL_CRATE).as_str()),
            fns.join(","),
            others.join(",")
        );
        match std::env::var_os("AGENT_RS_ITEMS_OUT") {
            Some(path) => {
                let mut f = std::fs::OpenOptions::new().create(true).append(true).open(path).expect("open output");
                f.write_all(doc.as_bytes()).expect("write output");
            }
            None => print!("{}", doc),
        }
        Compilation::Stop
    }
}

fn main() {
    let mut args: Vec<String> = std::env::args().collect();
    // RUSTC_WORKSPACE_WRAPPER mode: argv = [wrapper, rustc, args...]
    if args.len() > 1 && args[1].ends_with("rustc") {
        args.remove(1);
    }
    // Cargo probes `rustc -vV` / `--print`; let the real compiler answer those.
    rustc_driver::run_compiler(&args, &mut Items);
}
