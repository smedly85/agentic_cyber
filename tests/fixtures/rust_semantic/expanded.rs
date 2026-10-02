//! Synthetic instrument probes, not historical uutils source.
extern crate scopeguard;
#[inline(never)] fn target(x: usize) -> usize { std::hint::black_box(x + 1) }
#[inline(never)] fn third(x: usize) -> usize { std::hint::black_box(x + 3) }

#[repr(C)] struct Ops { a: fn(usize) -> usize, b: fn(usize) -> usize }
static OPS: Ops = Ops { a: third, b: target };
#[inline(never)] fn by_reference(ops: &Ops, x: usize) -> usize { (ops.b)(x) }
#[inline(never)] fn static_table(x: usize) -> usize { (OPS.b)(x) }
#[inline(never)] fn stack_fields(x: usize) -> usize {
    let ops = Ops { a: third, b: target };
    by_reference(&ops, x)
}

trait Action { fn operation(&self, x: usize) -> usize; fn multiple(&self, x: usize, y: usize) -> usize; }
struct First;
struct Second;
impl Action for First {
    #[inline(never)] fn operation(&self, x: usize) -> usize { target(x) }
    #[inline(never)] fn multiple(&self, x: usize, y: usize) -> usize { target(x + y) }
}
impl Action for Second {
    #[inline(never)] fn operation(&self, x: usize) -> usize { third(x) }
    #[inline(never)] fn multiple(&self, x: usize, y: usize) -> usize { third(x + y) }
}
impl Drop for First { #[inline(never)] fn drop(&mut self) { std::hint::black_box(1); } }
#[inline(never)] fn dyn_one(a: &dyn Action, x: usize) -> usize { a.operation(x) }
#[inline(never)] fn dyn_many(a: &dyn Action, x: usize) -> usize { a.multiple(x, 2) }
#[inline(never)] fn boxed(x: usize) -> usize { let a: Box<dyn Action> = Box::new(First); a.operation(x) }
#[inline(never)] fn dyn_fn(f: &dyn Fn(usize) -> usize, x: usize) -> usize { f(x) }
#[inline(never)] fn boxed_mut(x: usize) -> usize { let mut f: Box<dyn FnMut(usize) -> usize> = Box::new(|v| target(v)); f(x) }
#[inline(never)] fn option_path(x: usize) -> usize { Some(x).map(|v| target(v)).unwrap_or(0) }
#[inline(never)] fn result_path(x: usize) -> usize { Err::<usize,usize>(x).or_else(|v| Ok::<usize,usize>(target(v))).unwrap_or(0) }
#[inline(never)] fn iterator_path(x: usize) -> usize { [x].into_iter().flat_map(|v| [target(v)]).sum() }

trait Args { fn value(&self) -> usize; }
struct Arguments(usize);
impl Args for Arguments { #[inline(never)] fn value(&self) -> usize { self.0 } }
// Representative mechanical outer/inner shape, without importing uutils code.
#[inline(never)] fn uumain(args: impl Args) -> usize {
    #[inline(never)] fn uumain(args: impl Args) -> usize { target(args.value()) }
    uumain(args)
}
#[inline(never)] fn startup(x: usize) -> usize { uumain(Arguments(x)) }

#[inline(never)] fn may_panic(x: usize) -> usize { if x == 0 { panic!("controlled"); } target(x) }
#[inline(never)] fn unwind_path(x: usize) -> usize { let _drop = First; may_panic(x) }
#[inline(never)] fn dependency_path(x: usize) -> usize {
    let guard = scopeguard::guard(x, |v| { target(v); });
    drop(guard);
    x
}
#[inline(never)] fn static_and_dynamic(x: usize) -> usize {
    let a = First;
    a.operation(x) + dyn_one(&a, x)
}
#[cfg(target_os="linux")]
#[inline(never)] fn platform_path(x: usize) -> usize { target(x) }
#[cfg(not(target_os="linux"))]
#[inline(never)] fn platform_path(x: usize) -> usize { third(x) }
#[inline(never)] fn same_named(x: usize) -> usize {
    First.operation(x) + Second.operation(x)
}

fn main() {
    let x = std::hint::black_box(1usize);
    #[cfg(audit_case="nonfirst_reference")] { by_reference(&OPS, x); }
    #[cfg(audit_case="static_table")] { static_table(x); }
    #[cfg(audit_case="trait_drop")] { dyn_one(&First, x); }
    #[cfg(audit_case="trait_one")] { dyn_one(&First, x); }
    #[cfg(audit_case="trait_many")] { dyn_many(&First, x); }
    #[cfg(audit_case="box_trait")] { boxed(x); }
    #[cfg(audit_case="dyn_fn")] { dyn_fn(&|v| target(v), x); }
    #[cfg(audit_case="box_fnmut")] { boxed_mut(x); }
    #[cfg(audit_case="option_map")] { option_path(x); }
    #[cfg(audit_case="result_or_else")] { result_path(x); }
    #[cfg(audit_case="iterator_flat_map")] { iterator_path(x); }
    #[cfg(audit_case="entry_wrappers")] { startup(x); }
    #[cfg(audit_case="unwind")] { unwind_path(x); }
    #[cfg(audit_case="crates_io")] { dependency_path(x); }
    #[cfg(audit_case="static_and_dyn")] { static_and_dynamic(x); }
    #[cfg(audit_case="platform")] { platform_path(x); }
    #[cfg(audit_case="stack_bytes")] { stack_fields(x); }
    #[cfg(audit_case="same_method")] { same_named(x); }
}
