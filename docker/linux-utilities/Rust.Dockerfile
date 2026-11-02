ARG RUST_IMAGE=rust:1.85.1-bookworm@sha256:e51d0265072d2d9d5d320f6a44dde6b9ef13653b035098febd68cce8fa7c0bc4
ARG PYTHON_IMAGE=python:3.12.8-bookworm@sha256:68ca65265c466f4b64f8ddab669e13bcba8d4ba77ec4c26658d36f2b9d1b1cad
FROM ${RUST_IMAGE} AS rust
FROM ${PYTHON_IMAGE}
COPY --from=rust /usr/local/rustup /usr/local/rustup
COPY --from=rust /usr/local/cargo /usr/local/cargo
ENV RUSTUP_HOME=/usr/local/rustup CARGO_HOME=/usr/local/cargo PATH=/usr/local/cargo/bin:$PATH
ENV LC_ALL=C LANG=C TZ=UTC PYTHONDONTWRITEBYTECODE=1
RUN rustc --version | grep '^rustc 1.85.1 ' && test "$(python3 --version)" = 'Python 3.12.8'
USER 1000:1000
WORKDIR /tmp
