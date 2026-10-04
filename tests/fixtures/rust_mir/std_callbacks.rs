#[inline(never)] fn sort_target(a:i32,b:i32)->std::cmp::Ordering {a.cmp(&b)}
#[inline(never)] fn boxed_target(a:i32)->i32 {std::hint::black_box(a+1)}
fn main(){
    let compare:fn(i32,i32)->std::cmp::Ordering=sort_target;
    let mut values=[3,1,2];
    values.sort_by(|a,b|compare(*a,*b));
    let mut callback:Box<dyn FnMut(i32)->i32>=Box::new(|value|boxed_target(value));
    let sum:i32=values.into_iter().map(|value|callback(value)).sum();
    std::hint::black_box(sum);
}
