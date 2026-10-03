//! Controlled-only core capability probes.
type Callback = fn(u64) -> u64;
#[repr(C)]
struct Ops { first: Callback, second: Callback }
#[inline(never)] fn target(x:u64)->u64 { x }
#[inline(never)] fn other(x:u64)->u64 { x }
#[inline(never)] fn unrelated(x:u64)->u64 { x }
#[inline(never)] fn third(x:u64)->u64 { x }
static STATIC_OPS:Ops=Ops{first:unrelated,second:third};
#[inline(never)] fn invoke(o:&Ops,x:u64)->u64 { (o.second)(x) }
#[inline(never)] fn invoke_separate(o:&Ops,x:u64)->u64 { (o.second)(x) }
#[inline(never)] fn transfer(o:Box<Ops>)->Box<Ops> { let moved=o; moved }
#[inline(never)] fn allocate(f:Callback)->Box<Ops> { Box::new(Ops{first:unrelated,second:f}) }
trait Action { fn operation(&self,x:u64,y:u64)->u64; }
struct First;
struct Second;
struct Unrelated;
impl Action for First { #[inline(never)] fn operation(&self,x:u64,_y:u64)->u64 { target(x) } }
impl Action for Second { #[inline(never)] fn operation(&self,x:u64,_y:u64)->u64 { other(x) } }
impl Action for Unrelated { #[inline(never)] fn operation(&self,x:u64,_y:u64)->u64 { unrelated(x) } }
impl Drop for First { #[inline(never)] fn drop(&mut self) { std::hint::black_box(1); } }
#[inline(never)] fn dynamic(o:&dyn Action,x:u64)->u64 { o.operation(x,2) }
#[inline(never)] fn pass_closure<F:Fn(u64)->u64>(f:F,x:u64)->u64 { f(x) }
#[inline(never)] fn make_closure(f:Callback)->impl Fn(u64)->u64 { move |x| f(x) }
struct ClosureHolder<F> { ignored:Callback, closure:F }
#[inline(never)] fn closure_capture(x:u64)->u64 { let f:Callback=target;let c=move |v| f(v);c(x) }
#[inline(never)] fn closure_arg(x:u64)->u64 { let f:Callback=target;pass_closure(move |v| f(v),x) }
#[inline(never)] fn closure_return(x:u64)->u64 { let f=make_closure(target);f(x) }
#[inline(never)] fn closure_object(x:u64)->u64 { let o=Ops{first:unrelated,second:target};let c=move |v| invoke(&o,v);c(x) }
#[inline(never)] fn closure_struct(x:u64)->u64 { let f:Callback=target;let h=ClosureHolder{ignored:unrelated,closure:move |v| f(v)};(h.closure)(x) }
#[inline(never)] fn closure_box(x:u64)->u64 { let f:Callback=target;let c=Box::new(move |v| f(v));c(x) }
#[inline(never)] fn dyn_fn_site(f:&dyn Fn(u64)->u64,x:u64)->u64 { f(x) }
#[inline(never)] fn closure_dyn(x:u64)->u64 { let f:Callback=target;let c=move |v| f(v);dyn_fn_site(&c,x) }
#[inline(never)] fn dyn_fnmut_site(f:&mut dyn FnMut(u64)->u64,x:u64)->u64 { f(x) }
#[inline(never)] fn closure_fnmut(x:u64)->u64 {
    let f:Callback=target;let mut captured=0;
    let mut c:Box<dyn FnMut(u64)->u64>=Box::new(move |v| { captured=v;f(captured) });
    dyn_fnmut_site(&mut *c,x)
}
#[inline(never)] fn closure_tuple_args(x:u64)->u64 { let c=|f:Callback,v| f(v);c(target,x) }
#[inline(never)] fn closure_once(x:u64)->u64 { let b=Box::new(Ops{first:unrelated,second:target});let c=move || {let moved=b;invoke(&moved,x)};c() }
#[inline(never)] fn unsafe_copy(o:Ops)->Ops { unsafe {
    let mut dst=std::mem::MaybeUninit::<Ops>::uninit();
    std::ptr::copy_nonoverlapping((&o as *const Ops).cast::<u8>(),dst.as_mut_ptr().cast::<u8>(),std::mem::size_of::<Ops>());
    dst.assume_init()
} }
#[inline(never)] fn unsafe_cast_read(x:u64)->u64 { let o=Ops{first:other,second:target};unsafe { let f=*(&o as *const Ops).cast::<Callback>();f(x) } }
union Alias { value:std::mem::ManuallyDrop<Ops>, callback:Callback }
#[inline(never)] fn unsafe_union(x:u64)->u64 { let u=Alias{value:std::mem::ManuallyDrop::new(Ops{first:other,second:target})};unsafe { (u.callback)(x) } }
#[inline(never)] fn unsafe_transmute(x:u64)->u64 { let o=Ops{first:other,second:target};let p:(Callback,Callback)=unsafe {std::mem::transmute(o)};(p.1)(x) }
#[inline(never)] fn unsafe_offset(x:u64)->u64 { let o=Ops{first:other,second:target};unsafe { let f=*(&o as *const Ops).cast::<Callback>().add((x&1)as usize);f(x) } }
#[inline(never)] fn mixed_callable(x:u64)->u64 { let f:Callback=other;let c=|v|target(v);let r:&dyn Fn(u64)->u64=if x==0 {&f}else{&c};dyn_fn_site(r,x) }
fn main() {
    let x=std::hint::black_box(1u64);
    #[cfg(core_case="heap_single")] {
        let a=Box::new(Ops{first:unrelated,second:target});
        invoke(&a,x);
    }
    #[cfg(core_case="heap_two")] {
        let a=Box::new(Ops{first:unrelated,second:target});
        let b=Box::new(Ops{first:unrelated,second:other});
        let r=if x==0 { &*a } else { &*b }; invoke(r,x);
    }
    #[cfg(core_case="heap_stack")] {
        let a=Ops{first:unrelated,second:target};
        let b=Box::new(Ops{first:unrelated,second:other});
        let r=if x==0 { &a } else { &*b }; invoke(r,x);
    }
    #[cfg(core_case="heap_helpers")] {
        let a=allocate(target);let b=transfer(a);invoke(&b,x);
    }
    #[cfg(core_case="heap_isolation")] {
        let a=Box::new(Ops{first:unrelated,second:target});
        let b=Box::new(Ops{first:unrelated,second:other});
        invoke(&a,x);invoke_separate(&b,x);
    }
    #[cfg(core_case="dyn_one")] { dynamic(&First,x); }
    #[cfg(core_case="dyn_two")] {
        let a=First;let b=Second;let r:&dyn Action=if x==0 {&a} else {&b};
        let unused:&dyn Action=&Unrelated;std::hint::black_box(unused);dynamic(r,x);
    }
    #[cfg(core_case="dyn_box")] { let a:Box<dyn Action>=Box::new(First);dynamic(&*a,x); }
    #[cfg(core_case="dyn_static")] { let a=First;a.operation(x,2);dynamic(&a,x); }
    #[cfg(core_case="dyn_drop")] { let a=First;dynamic(&a,x);drop(a); }
    #[cfg(core_case="dyn_multiarg")] { dynamic(&Second,x); }
    #[cfg(core_case="closure_capture")] { closure_capture(x); }
    #[cfg(core_case="closure_arg")] { closure_arg(x); }
    #[cfg(core_case="closure_return")] { closure_return(x); }
    #[cfg(core_case="closure_object")] { closure_object(x); }
    #[cfg(core_case="closure_struct")] { closure_struct(x); }
    #[cfg(core_case="closure_box")] { closure_box(x); }
    #[cfg(core_case="closure_dyn")] { closure_dyn(x); }
    #[cfg(core_case="closure_fnmut")] { closure_fnmut(x); }
    #[cfg(core_case="closure_tuple_args")] { closure_tuple_args(x); }
    #[cfg(core_case="closure_once")] { closure_once(x); }
    #[cfg(core_case="unsafe_byte")] { let o=unsafe_copy(Ops{first:other,second:target});invoke(&o,x); }
    #[cfg(core_case="unsafe_cast_read")] { unsafe_cast_read(x); }
    #[cfg(core_case="unsafe_union")] { unsafe_union(x); }
    #[cfg(core_case="unsafe_transmute")] { unsafe_transmute(x); }
    #[cfg(core_case="unsafe_offset")] { unsafe_offset(x); }
    #[cfg(core_case="mixed_storage")] {
        let a=Ops{first:unrelated,second:target};let b=Box::new(Ops{first:unrelated,second:other});
        let r=if x==0 {&a}else if x==1 {&*b}else{&STATIC_OPS};invoke(r,x);
    }
    #[cfg(core_case="mixed_callable")] { mixed_callable(x); }
    #[cfg(core_case="mixed_dyn_static")] {
        let a=First;let b=Second;a.operation(x,2);let r:&dyn Action=if x==0 {&a}else{&b};dynamic(r,x);
    }
    #[cfg(core_case="mixed_safe_unsafe")] {
        let a=Ops{first:unrelated,second:target};let b=unsafe_copy(Ops{first:other,second:third});
        let r=if x==0 {&a}else{&b};invoke(r,x);
    }
}
