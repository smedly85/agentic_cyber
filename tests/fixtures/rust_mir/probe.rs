//! Controlled stage/identity probe only; no historical or candidate utility code.
#[inline(never)] fn target(x: u8)->u8 { x }
#[inline(never)] fn other(x: u8)->u8 { x.wrapping_add(1) }
#[inline(never)] fn a(x: u8)->u8 { target(x) }
#[inline(never)] fn generic<T: Copy>(x:T)->T { x }
struct Ops { a: fn(u8)->u8, b: fn(u8)->u8 }
#[inline(never)] fn fields(ops:&Ops,x:u8)->u8 { (ops.b)((ops.a)(x)) }
trait Action { fn operation(&self,x:u8)->u8; }
struct First;
impl Action for First { fn operation(&self,x:u8)->u8 { target(x) } }
#[inline(never)] fn dynamic(x:&dyn Action,v:u8)->u8 { x.operation(v) }
fn main() {
    let x=std::hint::black_box(7);
    let ops=Ops{a:other,b:target};
    let _=a(x);
    let _=fields(&ops,x);
    let _=generic::<u8>(x);
    let _=generic::<u16>(x as u16);
    let _=Some(x).map(target);
    let receiver:Box<dyn Action>=Box::new(First);
    let _=dynamic(&*receiver,x);
}
