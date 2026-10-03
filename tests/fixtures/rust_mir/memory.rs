//! Controlled allocation/field adversaries. No historical source.
type Callback = fn(u64) -> u64;
#[derive(Clone, Copy)]
struct Ops { first: Callback, second: Callback, third: Callback }
#[inline(never)] fn target(x: u64) -> u64 { x }
#[inline(never)] fn other(x: u64) -> u64 { x }
#[inline(never)] fn third(x: u64) -> u64 { x }
#[inline(never)] fn invoke_first(o: &Ops, x: u64) -> u64 { (o.first)(x) }
#[inline(never)] fn invoke_second(o: &Ops, x: u64) -> u64 { (o.second)(x) }
#[inline(never)] fn invoke_third(o: &Ops, x: u64) -> u64 { (o.third)(x) }
fn main() {
    let x = std::hint::black_box(1);
    let mut o = Ops { first: other, second: target, third };
    #[cfg(memory_case="first_field")] { invoke_first(&o, x); }
    #[cfg(memory_case="second_field")] { invoke_second(&o, x); }
    #[cfg(memory_case="three_fields")] { invoke_first(&o, x); invoke_second(&o, x); invoke_third(&o, x); }
    #[cfg(memory_case="reversed_writes")] {
        let mut r: Ops;
        r = Ops { third, second: target, first: other };
        invoke_second(&r, x);
    }
    #[cfg(memory_case="overwrite")] { o.second = other; invoke_second(&o, x); }
    #[cfg(memory_case="conditional_same_field")] {
        if x == 0 { o.second = other; } else { o.second = target; }
        invoke_second(&o, x);
    }
    #[cfg(memory_case="distinct_fields")] { invoke_first(&o, x); invoke_second(&o, x); }
    #[cfg(memory_case="stack_copy")] { let copied = o; invoke_second(&copied, x); }
    #[cfg(memory_case="heap_storage")] { let heap = Box::new(o); invoke_second(&heap, x); }
    #[cfg(memory_case="mixed_objects")] {
        let p = Ops { first: third, second: other, third: target };
        let r = if x == 0 { &o } else { &p };
        invoke_second(r, x);
    }
    #[cfg(memory_case="stack_heap")] {
        let p = Box::new(Ops { first: third, second: other, third: target });
        let r = if x == 0 { &o } else { &*p };
        invoke_second(r, x);
    }
    #[cfg(memory_case="unsafe_bytes")] unsafe {
        let mut p = std::mem::MaybeUninit::<Ops>::uninit();
        std::ptr::copy_nonoverlapping((&o as *const Ops).cast::<u8>(),
            p.as_mut_ptr().cast::<u8>(), std::mem::size_of::<Ops>());
        let p = p.assume_init();
        invoke_second(&p, x);
    }
}
