# Every image the repository uses, one stage each. Build from the repository root
# with src/ as the context:
#
#   docker build -f docker/Dockerfile --target agent-c    -t agent-c    src
#   docker build -f docker/Dockerfile --target agent-rust -t agent-rust src
#   docker build -f docker/Dockerfile --target oracle     -t agentic-linux-utilities      src
#   docker build -f docker/Dockerfile --target rust-jail  -t agentic-linux-utilities-rust src
#
# agent-*: toolchain + call-graph backend + mini-swe-agent for the agent sessions.
# oracle:  GNU Coreutils 9.11 and GNU grep 3.12 reference binaries (never given candidates).
# rust-jail: the Rust compiler the benchmark builds candidates with (C uses PYTHON_IMAGE).
# Benchmark image IDs are pinned in coreutils/images.lock.json; agent image IDs are
# recorded in each run's manifest.

ARG UBUNTU_IMAGE=ubuntu@sha256:73b999393d07f2bf65a40373778a44dc9a6d54ad7718d29247d8ff9413c4d6a8
ARG PYTHON_IMAGE=python:3.12.8-bookworm@sha256:68ca65265c466f4b64f8ddab669e13bcba8d4ba77ec4c26658d36f2b9d1b1cad
ARG RUST_IMAGE=rust:1.85.1-bookworm@sha256:e51d0265072d2d9d5d320f6a44dde6b9ef13653b035098febd68cce8fa7c0bc4

# ---------------------------------------------------------------- agent images
FROM ${UBUNTU_IMAGE} AS agent-base
ARG MINI_SWE_AGENT_VERSION=2.4.6
ENV DEBIAN_FRONTEND=noninteractive LANG=C.UTF-8 AGENT_PYTHON=/opt/agent/bin/python
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl git build-essential python3 python3-venv python3-pip \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m venv /opt/agent \
    && /opt/agent/bin/pip install --no-cache-dir mini-swe-agent==${MINI_SWE_AGENT_VERSION}
WORKDIR /work

FROM agent-base AS agent-c
ARG LLVM_MAJOR=21
ARG SVF_COMMIT=67efb7745ce47b2b6853fd5696fc22c83d701e6c
# LLVM/Clang 21 from apt.llvm.org (the pinned SVF commit requires LLVM 21).
RUN apt-get update && apt-get install -y --no-install-recommends \
        wget gnupg lsb-release software-properties-common unzip xz-utils \
    && curl -fsSL https://apt.llvm.org/llvm.sh -o /tmp/llvm.sh \
    && bash /tmp/llvm.sh ${LLVM_MAJOR} \
    && apt-get install -y --no-install-recommends \
        llvm-${LLVM_MAJOR}-dev libclang-${LLVM_MAJOR}-dev clang-${LLVM_MAJOR} lld-${LLVM_MAJOR} \
        libzstd-dev zlib1g-dev libncurses-dev libxml2-dev libedit-dev libcurl4-openssl-dev \
    && rm -rf /var/lib/apt/lists/* /tmp/llvm.sh \
    && for t in clang clang++ llvm-link llvm-dis opt llvm-config; do \
         ln -sf /usr/lib/llvm-${LLVM_MAJOR}/bin/$t /usr/local/bin/$t; done
# SVF at its pinned commit, with the repository's semantic call-graph helper.
RUN python3 -m venv /opt/svf-tools \
    && /opt/svf-tools/bin/pip install --no-cache-dir cmake==3.31.6 ninja==1.11.1.3 \
    && git init /opt/SVF \
    && git -C /opt/SVF remote add origin https://github.com/SVF-tools/SVF.git \
    && git -C /opt/SVF fetch --depth 1 origin ${SVF_COMMIT} \
    && git -C /opt/SVF checkout --detach ${SVF_COMMIT}
COPY analyzers/native/ /opt/SVF/svf-llvm/tools/SemanticCallGraph/
RUN printf '\nadd_subdirectory(SemanticCallGraph)\n' >> /opt/SVF/svf-llvm/tools/CMakeLists.txt \
    && cd /opt/SVF \
    && PATH=/opt/svf-tools/bin:$PATH LLVM_DIR=/usr/lib/llvm-${LLVM_MAJOR} SVF_BUILD_JOBS=8 bash ./build.sh \
    && helper=$(find /opt/SVF -type f -name semantic-callgraph-svf -perm -u+x | head -n1) \
    && test -n "$helper" && ln -sf "$helper" /usr/local/bin/semantic-callgraph-svf \
    && rm -rf /opt/SVF/Release-build/CMakeFiles
ENV AGENT_IMAGE_LANGUAGE=c AGENT_SVF_HELPER=/usr/local/bin/semantic-callgraph-svf

FROM agent-base AS agent-rust
ARG RUST_VERSION=1.93.0
ARG RUPTA_NIGHTLY=nightly-2024-02-03
ARG RUPTA_COMMIT=b19f187e9cbe37b5afb1103d88b663253e1f0a03
ENV RUSTUP_HOME=/opt/rustup CARGO_HOME=/opt/cargo PATH=/opt/cargo/bin:$PATH
RUN apt-get update && apt-get install -y --no-install-recommends pkg-config libssl-dev \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL https://static.rust-lang.org/rustup/dist/x86_64-unknown-linux-gnu/rustup-init -o /tmp/rustup-init \
    && chmod +x /tmp/rustup-init \
    && /tmp/rustup-init -y --no-modify-path --profile minimal --default-toolchain ${RUST_VERSION} \
    && rm /tmp/rustup-init \
    && rustup component add --toolchain ${RUST_VERSION} rustc-dev rust-src llvm-tools \
    && rustup toolchain install ${RUPTA_NIGHTLY} --profile minimal \
         --component rust-src,rustc-dev,llvm-tools-preview
# RUPTA (pta, cargo-pta) at its pinned commit.
RUN git init /opt/rupta \
    && git -C /opt/rupta remote add origin https://github.com/rustanlys/rupta.git \
    && git -C /opt/rupta fetch --depth 1 origin ${RUPTA_COMMIT} \
    && git -C /opt/rupta checkout --detach ${RUPTA_COMMIT} \
    && cd /opt/rupta && cargo +${RUPTA_NIGHTLY} build --locked --release -j 8 \
    && install -m 0755 target/release/pta target/release/cargo-pta /usr/local/bin/ \
    && rm -rf target
# The repository's rustc_private tools: MIR call-graph probe and item inventory.
COPY analyzers/mir_driver.rs incontainer/rs_items.rs /opt/mir/
RUN SYSROOT=$(rustc +${RUST_VERSION} --print sysroot) \
    && for tool in mir_driver:mir-probe rs_items:rs-items; do \
         RUSTC_BOOTSTRAP=1 rustc +${RUST_VERSION} /opt/mir/${tool%%:*}.rs --edition=2021 -C prefer-dynamic \
           -L "$SYSROOT/lib" -o /usr/local/bin/${tool##*:}; done \
    && printf '%s\n' "$SYSROOT/lib" "$SYSROOT/lib/rustlib/x86_64-unknown-linux-gnu/lib" > /etc/ld.so.conf.d/rust-sysroot.conf \
    && ldconfig \
    && chmod -R a+rwX /opt/rustup /opt/cargo
ENV AGENT_IMAGE_LANGUAGE=rust AGENT_RUST_VERSION=${RUST_VERSION} AGENT_RUPTA_TOOLCHAIN=${RUPTA_NIGHTLY}

# ------------------------------------------------------------ benchmark images
FROM ${PYTHON_IMAGE} AS oracle
ARG PYTHON_IMAGE
ARG TARGETARCH
ENV LC_ALL=C LANG=C LANGUAGE=C TZ=UTC PYTHONDONTWRITEBYTECODE=1
# A fixed Debian snapshot pins every transitive package input.
RUN rm -f /etc/apt/sources.list /etc/apt/sources.list.d/* \
 && printf '%s\n' 'deb [check-valid-until=no] https://snapshot.debian.org/archive/debian/20250201T000000Z bookworm main' > /etc/apt/sources.list \
 && apt-get -o Acquire::Check-Valid-Until=false update \
 && apt-get install -y --no-install-recommends gcc make libc6-dev curl xz-utils \
 && test "$(gcc -dumpfullversion)" = 12.2.0 \
 && test "$(python3 --version)" = 'Python 3.12.8' \
 && rm -rf /var/lib/apt/lists/*
# Source SHA-256s are from GNU's signed release announcements:
#   coreutils 9.11 https://lists.gnu.org/archive/html/coreutils-announce/2026-04/msg00000.html
#   grep 3.12      https://lists.gnu.org/archive/html/info-gnu/2025-04/msg00008.html
RUN set -e; fetch() { \
      curl --fail --location --proto '=https' --tlsv1.2 "https://ftp.gnu.org/gnu/$1/$1-$2.tar.xz" -o /tmp/src.tar.xz; \
      echo "$3  /tmp/src.tar.xz" | sha256sum -c -; \
      rm -rf /tmp/build && mkdir /tmp/build && tar -xJf /tmp/src.tar.xz --strip-components=1 -C /tmp/build; \
      cd /tmp/build && FORCE_UNSAFE_CONFIGURE=1 ./configure --prefix=/opt/gnu --disable-nls && make -j2 && make install; \
      cd / && rm -rf /tmp/build /tmp/src.tar.xz; }; \
    fetch coreutils 9.11 3940a4eda0a59552172eda9cd1201e65dca3a3aa29c29511349495a215a7c3cc; \
    fetch grep 3.12 2649b27c0e90e632eadcd757be06c6e9a4f48d941de51e7c0f83ff76408a07b9; \
    test "$(/opt/gnu/bin/grep --version | head -1)" = 'grep (GNU grep) 3.12'; \
    useradd --uid 1000 --create-home benchmark; \
    mkdir /output /provenance; chown 1000:1000 /output; \
    dpkg-query -W > /provenance/packages.txt; \
    printf '%s\n' "$PYTHON_IMAGE" > /provenance/base-image.txt; \
    printf '%s\n' "$TARGETARCH" > /provenance/build-architecture.txt; \
    gcc --version > /provenance/compiler.txt; \
    /opt/gnu/bin/grep --version > /provenance/grep-version.txt; \
    sha256sum /opt/gnu/bin/grep > /provenance/grep-binary-sha256.txt
USER 1000:1000
VOLUME ["/output"]
WORKDIR /work
CMD ["python3", "src/harness/linux_benchmark.py", "verify"]

FROM ${RUST_IMAGE} AS rust-toolchain
FROM ${PYTHON_IMAGE} AS rust-jail
COPY --from=rust-toolchain /usr/local/rustup /usr/local/rustup
COPY --from=rust-toolchain /usr/local/cargo /usr/local/cargo
ENV RUSTUP_HOME=/usr/local/rustup CARGO_HOME=/usr/local/cargo PATH=/usr/local/cargo/bin:$PATH \
    LC_ALL=C LANG=C TZ=UTC PYTHONDONTWRITEBYTECODE=1
RUN rustc --version | grep '^rustc 1.85.1 ' && test "$(python3 --version)" = 'Python 3.12.8'
USER 1000:1000
WORKDIR /tmp
