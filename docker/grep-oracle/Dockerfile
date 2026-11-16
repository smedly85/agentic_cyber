# Separate GNU grep oracle extension. BASE_IMAGE must be an immutable validated
# linux-utilities image ID or repository digest; the Coreutils oracle is not
# rebuilt or replaced.
ARG BASE_IMAGE
FROM ${BASE_IMAGE}
ARG BASE_IMAGE
ARG TARGETARCH
USER 0:0

# SHA-256 is from the signed GNU grep 3.12 release announcement (2025-04-10):
# https://lists.gnu.org/archive/html/info-gnu/2025-04/msg00008.html
RUN curl --fail --location --proto '=https' --tlsv1.2 \
      https://ftp.gnu.org/gnu/grep/grep-3.12.tar.xz -o /tmp/grep-3.12.tar.xz \
 && python3 -c "import base64,hashlib,pathlib; p=pathlib.Path('/tmp/grep-3.12.tar.xz'); assert hashlib.sha256(p.read_bytes()).digest() == base64.b64decode('JkmyfA6Q5jLq3NdXvgbG6aT0jZQd5R58D4P/dkCKB7k=')" \
 && mkdir /tmp/grep-build \
 && tar -xJf /tmp/grep-3.12.tar.xz --strip-components=1 -C /tmp/grep-build \
 && cd /tmp/grep-build \
 && FORCE_UNSAFE_CONFIGURE=1 ./configure --prefix=/opt/gnu --disable-nls \
 && make -j2 \
 && make install \
 && test "$(/opt/gnu/bin/grep --version | head -1)" = 'grep (GNU grep) 3.12' \
 && printf '%s\n' '2649b27c0e90e632eadcd757be06c6e9a4f48d941de51e7c0f83ff76408a07b9  grep-3.12.tar.xz' > /provenance/grep-source-sha256.txt \
 && /opt/gnu/bin/grep --version > /provenance/grep-version.txt \
 && sha256sum /opt/gnu/bin/grep > /provenance/grep-binary-sha256.txt \
 && printf '%s\n' "$BASE_IMAGE" > /provenance/grep-base-image.txt \
 && printf '%s\n' "$TARGETARCH" > /provenance/grep-build-architecture.txt \
 && rm -rf /tmp/grep-build /tmp/grep-3.12.tar.xz

USER 1000:1000
WORKDIR /work
CMD ["python3", "scripts/linux_benchmark.py", "verify", "--utility", "c-grep"]
