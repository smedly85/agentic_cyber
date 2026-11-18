"""Call-graph analyzers the pipeline runs inside its images.

Vendored from agentic_cyber's security/semantic_callgraph (pinned behaviour,
unchanged code apart from import paths):

  svf_backend.py           C: clang bitcode -> SVF (Andersen) call graph -> BFS depth
  native/                  the SVF helper built into agent-c (docker/Dockerfile, stage agent-c)
  mir_driver.rs            rustc_private MIR call-graph driver built into agent-rust
  mir_graph.py             Rust lightweight MIR graph normalizer
  rupta_adapter.py         Rust RUPTA call-graph adapter
"""
