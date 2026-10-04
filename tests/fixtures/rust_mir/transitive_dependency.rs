pub trait Action { fn operation(&self, a: usize, b: usize) -> usize; }
pub struct First;
pub struct Second;
impl Action for First { #[inline(never)] fn operation(&self,a:usize,b:usize)->usize {a+b} }
impl Action for Second { #[inline(never)] fn operation(&self,a:usize,b:usize)->usize {a*b} }
#[inline(never)]
pub fn make(second:bool)->Box<dyn Action> {
    if second {Box::new(Second)} else {Box::new(First)}
}
