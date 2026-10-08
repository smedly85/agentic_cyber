# Final calibration provenance freeze

CALIBRATION-CORPUS-FINAL-REFREEZE — READY FOR FINAL PREREGISTRATION CHECK

Bundle SHA-256: `ed7ea699999445b3db2da1113637b4e19a00c7e07a77277bef48e984d6ca3024`

All 30 source hashes and every approved pair record are unchanged, including R1–R4, expected edges/targets, source identities, runtime inputs, ordinary build configuration and cross-language categories. No analyzer ran, no semantic graph output was inspected, no depth was calculated, and no historical Rust work occurred. Neither scientific backend was modified.

verify_instruments: PASS, including direct expected/resolved path and expected/actual SHA-256 reports for runtime components, immutable backend sources/driver, standard libraries and all 159 protected C artifacts. See corpus_instrument_integrity.json.

Validator/tamper controls: 73 passed. Controls include all requested runtime components, Clang path/hash, environment/model overrides, added transitive libraries and aggregate hash sensitivity. No scientific binary was overwritten.

Ordinary smoke evidence remains 30/30 compilations and 34/34 runtime configurations from the prior bundle, reused for byte-identical sources and identical build/runtime inputs; no smoke rerun was necessary in this provenance-only pass.

## C runtime identities

| Component | Canonical resolved path | SHA-256 | SONAME |
|---|---|---|---|
| analyzer executable | `$REPO/build/semantic-toolchain/SVF/Release-build/bin/semantic-callgraph-svf` | `ca8ce8cd9e7e264dd8db7e8e8d656765af876db3fbec878da4de0edcc882a7d2` |  |
| compiler | `/usr/lib/llvm-21/bin/clang` | `412bbe8c60571a1eb06f48fde89635033621caeb01a9b4ee76d46711bae8e932` |  |
| ELF_INTERPRETER | `/usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2` | `bda779ea9e9ad234f60315477d7cfd0bdde861cd8ddd9df8cdaf62f18c4cec14` | ld-linux-x86-64.so.2 |
| libLLVM.so.21.1 | `/usr/lib/x86_64-linux-gnu/libLLVM.so.21.1` | `12dca1fc2d9f5d4ff35315fc2aa3a97b615b41ec6a71d3ce545efb62c075d902` | libLLVM.so.21.1 |
| libSvfCore.so.3 | `$REPO/build/semantic-toolchain/SVF/Release-build/lib/libSvfCore.so.3.4` | `d3e3e98758f3c49b9d40f7e8433d509e2e241b0b9a6f7088695a745ad3ad61a7` | libSvfCore.so.3 |
| libSvfLLVM.so.3 | `$REPO/build/semantic-toolchain/SVF/Release-build/lib/libSvfLLVM.so.3.4` | `b32764579aa075733c469f18983448860b8c9fd556f874a8c57eb60ad93315a9` | libSvfLLVM.so.3 |
| libbsd.so.0 | `/usr/lib/x86_64-linux-gnu/libbsd.so.0.12.2` | `c71b8a0d7e94c5e34f6c328c5dd1ba7f325d3300c97a54a7c69ef9a6c2caa8b3` | libbsd.so.0 |
| libc.so.6 | `/usr/lib/x86_64-linux-gnu/libc.so.6` | `85e64f97e348786a8fb4d9f3d52fec289e2fb86bba20f0731dfe61990525e0f7` | libc.so.6 |
| libedit.so.2 | `/usr/lib/x86_64-linux-gnu/libedit.so.2.0.76` | `438090e1cd463d9f89c9259ce9e99f229eae56c857b5e525d581e338f61aa1ce` | libedit.so.2 |
| libffi.so.8 | `/usr/lib/x86_64-linux-gnu/libffi.so.8.2.0` | `1a0dc86f787f73e025a6e521056360afcbe70f2a82cd808132fefc2b4ee95daa` | libffi.so.8 |
| libgcc_s.so.1 | `/usr/lib/x86_64-linux-gnu/libgcc_s.so.1` | `9d339ecb409578d6a5d587e6c537a8f9589b8a13fefba30d167433a4b5758bee` | libgcc_s.so.1 |
| libm.so.6 | `/usr/lib/x86_64-linux-gnu/libm.so.6` | `1c488db6f4fe8cecb72456bc018de000b7a9b539c2994864b0416b5e8371b3d8` | libm.so.6 |
| libmd.so.0 | `/usr/lib/x86_64-linux-gnu/libmd.so.0.1.0` | `f115fa619f586e47ddfbec21bfd50069fbe5d21f388f8d9a07a984cb075d7efa` | libmd.so.0 |
| libstdc++.so.6 | `/usr/lib/x86_64-linux-gnu/libstdc++.so.6.0.35` | `5bb0d21308f123b6ad46c6f35b42cedfcb8d6d439a53aa3dae04d880aaffdde3` | libstdc++.so.6 |
| libtinfo.so.6 | `/usr/lib/x86_64-linux-gnu/libtinfo.so.6.6` | `085dbbe5dc38619276bdd0af37ae588969b1308baded09a2990ce8824a602912` | libtinfo.so.6 |
| libxml2.so.16 | `/usr/lib/x86_64-linux-gnu/libxml2.so.16.1.2` | `facb359e716bc2be5ca6a91e08ee07d79c0438737f25949b52f0ec1b952b4e33` | libxml2.so.16 |
| libz.so.1 | `/usr/lib/x86_64-linux-gnu/libz.so.1.3.1` | `47b61967895b30e8c0c6818dd633ffeb87711cf637c688f981896f0dd84ce23b` | libz.so.1 |
| libz3.so | `$REPO/build/semantic-toolchain/SVF/z3.obj/bin/libz3.so` | `65cad76bbd6b718ec0d64692a9c6a9fcc238a4934866234fb68e7e395f320de1` | libz3.so |
| libzstd.so.1 | `/usr/lib/x86_64-linux-gnu/libzstd.so.1.5.7` | `060eeb79531d435306665fd78329d8a9dd579f95876c5960bb67937825362a80` | libzstd.so.1 |
| extapi.bc | `$REPO/build/semantic-toolchain/SVF/Release-build/lib/extapi.bc` | `1ae4be9840392462ec9240ee83aac4d045ff59f1d9f4ce3356ee83b74070ce55` |  |

Compiler identity:
```text
Ubuntu clang version 21.1.8 (6ubuntu1)
Target: x86_64-pc-linux-gnu
Thread model: posix
InstalledDir: /usr/lib/llvm-21/bin
```

Analyzer ELF search policy: `{'NEEDED': ['libSvfLLVM.so.3', 'libLLVM.so.21.1', 'libSvfCore.so.3', 'libz3.so', 'libstdc++.so.6', 'libc.so.6'], 'RPATH': [], 'RUNPATH': ['$ORIGIN/../lib:/usr/lib/llvm-21/lib:/mnt/c/Users/sbutl/Documents/UofA School/Multi_Agent_Systems/summer_code_project/agentic_cyber/build/semantic-toolchain/SVF/Release-build:/mnt/c/Users/sbutl/Documents/UofA School/Multi_Agent_Systems/summer_code_project/agentic_cyber/build/semantic-toolchain/SVF/Release-build/lib:/mnt/c/Users/sbutl/Documents/UofA School/Multi_Agent_Systems/summer_code_project/agentic_cyber/build/semantic-toolchain/SVF/z3.obj/bin'], 'SONAME': []}`

Resolution policy:
```json
{
  "extapi_override": "Forbidden; no -extapi argument accepted",
  "gate": "runtime_provenance.pre_measurement_gate(language, exact_launch_environment, exact_helper_options) must succeed immediately before every future authorized analyzer launch; no environment/options changes after gate.",
  "helper_options": [
    "-stat=false",
    "-ff-eq-base"
  ],
  "required": {},
  "rustup_policy": "Not applicable",
  "substitution_policy": "Exact resolved paths, SHA-256, ELF metadata and complete dependency closure must match; no alternate SVF/library/model path or silent substitution.",
  "unset": [
    "LD_PRELOAD",
    "LD_AUDIT",
    "SVF_DIR",
    "LD_DEBUG",
    "LD_PROFILE",
    "LD_TRACE_LOADED_OBJECTS",
    "LD_LIBRARY_PATH"
  ],
  "working_directory": "$REPO"
}
```

The complete compiler dependency closure (also frozen) is in fixture_manifest.json. No llvm-link invocation is required for these single-file C fixtures.

External model selection: ExtAPI::getExtBcPath: no setter in helper, empty default -extapi, compiled SVF_BUILD_DIR candidate, SVF_DIR unset, npm root candidate, then loaded libSvfCore directory. First existing candidate wins.
Observed candidates: `[{'exists': False, 'path': '/lib/extapi.bc'}, {'exists': True, 'path': '$REPO/build/semantic-toolchain/SVF/Release-build/lib/extapi.bc'}]`. npm is absent; /lib/extapi.bc is absent. The selected model is beside the loaded libSvfCore. The verifier rejects changed selection, model bytes or override options.

## Rust runtime identities

| Component | Canonical resolved path | SHA-256 | SONAME |
|---|---|---|---|
| analyzer executable | `$REPO/build/rust-mir/continuation/cast-final-v2/driver` | `2387d9cd86805df16d2ce5a4fe682f69b68e5998b4034f41bd35b23a682202ef` |  |
| compiler | `$REPO/build/rust-mir/toolchain/bin/rustc` | `d32249a7c3bfcfc67b471460386e46323accae7125e344567a12d5664d99bb57` |  |
| ELF_INTERPRETER | `/usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2` | `bda779ea9e9ad234f60315477d7cfd0bdde861cd8ddd9df8cdaf62f18c4cec14` | ld-linux-x86-64.so.2 |
| libLLVM.so.21.1-rust-1.93.0-stable | `$REPO/build/rust-mir/toolchain/lib/libLLVM.so.21.1-rust-1.93.0-stable` | `2292c5e38f58b7dddbce9b6fde924413db33b1e7424cf7499eae5c27eeef9923` | libLLVM.so.21.1-rust-1.93.0-stable |
| libc.so.6 | `/usr/lib/x86_64-linux-gnu/libc.so.6` | `85e64f97e348786a8fb4d9f3d52fec289e2fb86bba20f0731dfe61990525e0f7` | libc.so.6 |
| libdl.so.2 | `/usr/lib/x86_64-linux-gnu/libdl.so.2` | `59d725ca30596a9863f4fa2552a7125f834842abc86b40890231c129358965d2` | libdl.so.2 |
| libgcc_s.so.1 | `/usr/lib/x86_64-linux-gnu/libgcc_s.so.1` | `9d339ecb409578d6a5d587e6c537a8f9589b8a13fefba30d167433a4b5758bee` | libgcc_s.so.1 |
| libm.so.6 | `/usr/lib/x86_64-linux-gnu/libm.so.6` | `1c488db6f4fe8cecb72456bc018de000b7a9b539c2994864b0416b5e8371b3d8` | libm.so.6 |
| libpthread.so.0 | `/usr/lib/x86_64-linux-gnu/libpthread.so.0` | `1327fc40710691dbd94e88b6cf4efce27fefe8fbb93f7d1164a75b4dccaea696` | libpthread.so.0 |
| librt.so.1 | `/usr/lib/x86_64-linux-gnu/librt.so.1` | `9f3cc59207bcaaac74aaf7aca961f4816f0f4d945e4bd1c3cb98ec516becf161` | librt.so.1 |
| librustc_driver-90863c8161c83a53.so | `$REPO/build/rust-mir/toolchain/lib/librustc_driver-90863c8161c83a53.so` | `961473d6d032734a4c4443474bae128bd5396ecc486338fd34c5bf21edafed1f` | librustc_driver-90863c8161c83a53.so |
| libz.so.1 | `/usr/lib/x86_64-linux-gnu/libz.so.1.3.1` | `47b61967895b30e8c0c6818dd633ffeb87711cf637c688f981896f0dd84ce23b` | libz.so.1 |
| noprelude:alloc | `$REPO/build/rust-mir/build-std-probe/core-v1/target/x86_64-unknown-linux-gnu/debug/deps/liballoc-0d8a7b5ad1e7bc28.rlib` | `69db37e772ec566b8ba60ff0f98cf2bd92c008ce34b0384497778888a7df9a2d` |  |
| noprelude:compiler_builtins | `$REPO/build/rust-mir/build-std-probe/core-v1/target/x86_64-unknown-linux-gnu/debug/deps/libcompiler_builtins-be07a2748722135e.rlib` | `538f13a544d352b786dbd8bc0484f219108b12bdb3a53ef10f1b7583c45ec6eb` |  |
| noprelude:core | `$REPO/build/rust-mir/build-std-probe/core-v1/target/x86_64-unknown-linux-gnu/debug/deps/libcore-f8a58ea64da893b6.rlib` | `0c701de1a4615745a49b60bb328f661fd081cdd96d33514002ef651922d29618` |  |
| noprelude:panic_unwind | `$REPO/build/rust-mir/build-std-probe/core-v1/target/x86_64-unknown-linux-gnu/debug/deps/libpanic_unwind-6ba76888c3cf6651.rlib` | `2f21ba1914b9a7bda9f5f2e2e61ce61b951620dad27b5c17afa5f7677a76433e` |  |
| noprelude:proc_macro | `$REPO/build/rust-mir/build-std-probe/core-v1/target/x86_64-unknown-linux-gnu/debug/deps/libproc_macro-a6f8c422fea7c64b.rlib` | `b8c4aed088bd683ee94fb1cab5339029674087736be36116848cecc36551d069` |  |
| noprelude:std | `$REPO/build/rust-mir/build-std-probe/core-v1/target/x86_64-unknown-linux-gnu/debug/deps/libstd-a73d00d36c0cec1d.rlib` | `f94a0a8ce6b0aa0c3eaa749098314ab5bcdfec6a45cff170a9973fb7788fffd2` |  |

Compiler identity:
```text
rustc 1.93.0 (254b59607 2026-01-19)
binary: rustc
commit-hash: 254b59607d4417e9dffbc307138ae5c86280fe4c
commit-date: 2026-01-19
host: x86_64-unknown-linux-gnu
release: 1.93.0
LLVM version: 21.1.8
```

Analyzer ELF search policy: `{'NEEDED': ['librustc_driver-90863c8161c83a53.so', 'libgcc_s.so.1', 'libc.so.6'], 'RPATH': [], 'RUNPATH': [], 'SONAME': []}`

Resolution policy:
```json
{
  "extapi_override": "Forbidden; no -extapi argument accepted",
  "gate": "runtime_provenance.pre_measurement_gate(language, exact_launch_environment, exact_helper_options) must succeed immediately before every future authorized analyzer launch; no environment/options changes after gate.",
  "helper_options": [],
  "required": {
    "LD_LIBRARY_PATH": "$REPO/build/rust-mir/toolchain/lib:$REPO/build/rust-mir/toolchain/lib/rustlib/x86_64-unknown-linux-gnu/lib",
    "MIR_PROBE_TRANSITIVE": "1",
    "RUSTC_BOOTSTRAP": "1"
  },
  "rustup_policy": "No rustup launcher: direct pinned rustc/driver and explicit sysroot; RUSTUP_TOOLCHAIN unset.",
  "substitution_policy": "Exact resolved paths, SHA-256, ELF metadata and complete dependency closure must match; no alternate SVF/library/model path or silent substitution.",
  "unset": [
    "LD_PRELOAD",
    "LD_AUDIT",
    "SVF_DIR",
    "LD_DEBUG",
    "LD_PROFILE",
    "LD_TRACE_LOADED_OBJECTS",
    "MIR_PROBE_CONTINUE",
    "MIR_PROBE_OUTPUT",
    "RUSTFLAGS",
    "RUSTC_WRAPPER",
    "RUSTC_WORKSPACE_WRAPPER",
    "RUSTUP_TOOLCHAIN"
  ],
  "working_directory": "$REPO"
}
```

The complete compiler dependency closure (also frozen) is in fixture_manifest.json. No llvm-link invocation is required for these single-file C fixtures.

Sysroot: `$REPO/build/rust-mir/toolchain`; direct pinned toolchain, no rustup dispatch. The complete driver closure contains one rustc-private library (librustc_driver); all additional resolved libraries, loader and rebuilt std artifacts are bound.

## Superseded identities

`065751bf5cfbd7233583fb123fc04fb5f22b2c02f035234a54ae12668ec5830a`: superseded_before_measurement; independent preregistration audit corrections R1-R5.

`522fe6d821711beac3cb687aa012823a1332b34ec3ff800bfdc32e821a8a8bda`: superseded_before_measurement; final independent preregistration audit identified incomplete dynamic analysis-runtime fingerprinting.

No analyzer output existed for either superseded corpus. Prior manifests, metadata and source bytes are archived under provenance.

Unchanged C helper: `ca8ce8cd9e7e264dd8db7e8e8d656765af876db3fbec878da4de0edcc882a7d2`.

Unchanged Rust calibration-start: `514e397d83f9fd2be32e42b69970861036c7251dd2a2dbf38591a6ad7ec76e20`. Candidate instrument sources and driver are hash-verified unchanged.

Paths use `$REPO` for the canonical repository root. Runtime gates expand this value and compare canonical resolved paths, never silently substitute files.

CALIBRATION-CORPUS-FINAL-REFREEZE — READY FOR FINAL PREREGISTRATION CHECK
