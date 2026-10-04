#![feature(core_intrinsics)]
type Callback=fn(u64)->u64;
#[inline(never)] fn target(x:u64)->u64{x+1}
#[inline(never)] fn other(x:u64)->u64{x+2}
#[inline(never)] fn unrelated(x:u64)->u64{x+3}
#[derive(Clone,Copy)] struct Ops{first:Callback,second:Callback}
const CALLBACK:Callback=target;
const OPS:Ops=Ops{first:other,second:target};
static STATIC_OPS:Ops=Ops{first:other,second:target};
#[inline(never)] fn invoke(f:Callback,x:u64)->u64{f(x)}
trait Action:Sync{fn run(&self,x:u64)->u64;}
struct First; struct Second; struct Excluded;
impl Action for First{#[inline(never)] fn run(&self,x:u64)->u64{target(x)}}
impl Action for Second{#[inline(never)] fn run(&self,x:u64)->u64{other(x)}}
impl Action for Excluded{#[inline(never)] fn run(&self,x:u64)->u64{unrelated(x)}}
const DYN:&dyn Action=&First;
#[inline(never)] fn dynamic(a:&dyn Action,x:u64)->u64{a.run(x)}
#[inline(never)] fn dynamic_mut(a:&mut dyn FnMut(u64)->u64,x:u64)->u64{a(x)}
#[inline(never)] fn boxed_a()->Box<dyn FnMut(u64)->u64>{let f:Callback=target;let mut n=1;Box::new(move|x|{n+=x;f(n)})}
#[inline(never)] fn boxed_b()->Box<dyn FnMut(u64)->u64>{let f:Callback=other;let mut n=2;Box::new(move|x|{n+=x;f(n)})}
fn main(){
 let x=std::hint::black_box(1u64);
 #[cfg(cast_case="constant_item")] {invoke(CALLBACK,x);}
 #[cfg(cast_case="constant_struct")] {invoke(OPS.second,x);}
 #[cfg(cast_case="static_struct")] {invoke(STATIC_OPS.second,x);}
 #[cfg(cast_case="constant_helper")] {let o=std::hint::black_box(OPS);invoke(o.second,x);}
 #[cfg(cast_case="constant_dyn")] {dynamic(DYN,x);}
 #[cfg(cast_case="repeat_known")] {let callbacks=[target;3];invoke(callbacks[1],x);}
 #[cfg(cast_case="repeat_variable")] {let callbacks=[target as Callback;3];invoke(callbacks[(x as usize)%3],x);}
 #[cfg(cast_case="mixed_known")] {let callbacks=[other as Callback,target];invoke(callbacks[1],x);}
 #[cfg(cast_case="mixed_variable")] {let callbacks=[other as Callback,target];invoke(callbacks[(x as usize)%2],x);}
 #[cfg(cast_case="box_two")] {let a:Box<dyn Action>=if x==0{Box::new(First)}else{Box::new(Second)};dynamic(&*a,x);let excluded=Excluded;std::hint::black_box(&excluded);}
 #[cfg(cast_case="box_fnmut_two")] {let mut a=if x==0{boxed_a()}else{boxed_b()};dynamic_mut(&mut *a,x);}
 #[cfg(cast_case="select_fields")] {let a=Ops{first:unrelated,second:target};let b=Ops{first:unrelated,second:other};let c=std::intrinsics::select_unpredictable(x==0,a,b);invoke(c.second,x);}
 #[cfg(cast_case="swap_fields")] {let mut a=Ops{first:unrelated,second:target};let mut b=Ops{first:unrelated,second:other};unsafe{std::intrinsics::typed_swap_nonoverlapping(&mut a,&mut b)};invoke(a.second,x);}
}
