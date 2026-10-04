"""One-way soundness check: runtime observations never alter static edges."""
def compare(observed, static):
    observed=set(observed);static=set(static)
    return {'missing_dynamic_edges':sorted(observed-static),
            'static_only_edges':sorted(static-observed)}
