use std::sync::LazyLock;
#[inline(never)] fn lazy_target() {}
#[inline(never)] fn tls_target() {}
#[inline(never)] fn lazy_init() -> fn() { lazy_target }
#[inline(never)] fn tls_init() -> fn() { tls_target }
static LAZY: LazyLock<fn()> = LazyLock::new(lazy_init);
thread_local! { static TLS: fn() = tls_init(); }
fn main() { (*LAZY)(); TLS.with(|f| f()); }
