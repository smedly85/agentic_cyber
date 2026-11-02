# BASE_IMAGE must be python:3.12.8-bookworm@sha256:<resolved manifest digest>.
# A mutable tag alone is deliberately insufficient (enforced by build.sh).
ARG BASE_IMAGE
FROM ${BASE_IMAGE}
ARG BASE_IMAGE
ARG TARGETARCH
ENV LC_ALL=C LANG=C LANGUAGE=C TZ=UTC PYTHONDONTWRITEBYTECODE=1
# Fixed Debian snapshot fixes all transitive package inputs. No current mirrors.
RUN rm -f /etc/apt/sources.list /etc/apt/sources.list.d/* \
 && printf '%s\n' 'deb [check-valid-until=no] https://snapshot.debian.org/archive/debian/20250201T000000Z bookworm main' > /etc/apt/sources.list \
 && apt-get -o Acquire::Check-Valid-Until=false update \
 && apt-get install -y --no-install-recommends gcc make libc6-dev curl xz-utils \
 && test "$(gcc -dumpfullversion)" = 12.2.0 \
 && test "$(python3 --version)" = 'Python 3.12.8' \
 && rm -rf /var/lib/apt/lists/*
# SHA-256 from GNU's signed release announcement, 2026-04-20:
# https://lists.gnu.org/archive/html/coreutils-announce/2026-04/msg00000.html
RUN curl --fail --location --proto '=https' --tlsv1.2 \
      https://ftp.gnu.org/gnu/coreutils/coreutils-9.11.tar.xz -o /tmp/coreutils.tar.xz \
 && python3 -c "import base64,hashlib,pathlib; assert hashlib.sha256(pathlib.Path('/tmp/coreutils.tar.xz').read_bytes()).digest() == base64.b64decode('OUAk7aCllVIXztqc0SAeZdyPo6opwpURNaSVIdV8PMM=')" \
 && mkdir /tmp/coreutils-build \
 && tar -xJf /tmp/coreutils.tar.xz --strip-components=1 -C /tmp/coreutils-build \
 && cd /tmp/coreutils-build \
 && FORCE_UNSAFE_CONFIGURE=1 ./configure --prefix=/opt/gnu --disable-nls \
 && make -j2 \
 && make install \
 && /opt/gnu/bin/cp --version | head -1 \
 && rm -rf /tmp/coreutils-build /tmp/coreutils.tar.xz
RUN useradd --uid 1000 --create-home benchmark \
 && mkdir /output \
 && chown 1000:1000 /output \
 && mkdir /provenance \
 && dpkg-query -W > /provenance/packages.txt \
 && printf '%s\n' "$BASE_IMAGE" > /provenance/base-image.txt \
 && printf '%s\n' "$TARGETARCH" > /provenance/build-architecture.txt \
 && gcc --version > /provenance/compiler.txt
USER 1000:1000
VOLUME ["/output"]
WORKDIR /work
CMD ["python3", "scripts/linux_benchmark.py", "verify"]
