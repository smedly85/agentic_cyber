use transitive_dependency::Action;
struct Holder { noise: usize, object: Option<Box<Box<dyn Action>>> }
#[inline(never)]
pub fn route(noise:usize, value:Box<dyn Action>, other:usize)->Box<dyn Action> {
    let holder=Holder { noise:noise+other, object:Some(Box::new(value)) };
    let captured=move || {std::hint::black_box(holder.noise);holder.object.unwrap()};
    *captured()
}
