"""MIR-owned, offline, hash-authenticated controlled dependency inputs."""
import hashlib
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEPENDENCIES = ROOT / 'build/rust-mir/dependencies'
SCOPEGUARD_SHA256 = '94143f37725109f92c262ed2cf5e59bce7498c01bcc1502d7b9afe439a4e9f49'

def scopeguard():
    archive = DEPENDENCIES / 'scopeguard-1.2.0.crate'
    if hashlib.sha256(archive.read_bytes()).hexdigest() != SCOPEGUARD_SHA256:
        raise ValueError('scopeguard archive fingerprint mismatch')
    source = DEPENDENCIES / 'scopeguard-1.2.0'
    expected = set()
    with tarfile.open(archive) as bundle:
        for member in bundle.getmembers():
            relative = Path(member.name)
            if relative.is_absolute() or '..' in relative.parts or relative.parts[0] != source.name:
                raise ValueError('Unsafe dependency archive member')
            if member.isdir():continue
            if not member.isfile():raise ValueError('Unexpected dependency archive link')
            path = DEPENDENCIES / relative
            if path.read_bytes() != bundle.extractfile(member).read():
                raise ValueError('scopeguard source differs from authenticated archive: '+member.name)
            expected.add(path.relative_to(source).as_posix())
    actual = {p.relative_to(source).as_posix() for p in source.rglob('*') if p.is_file()}
    if actual != expected:raise ValueError('Unexpected scopeguard source files')
    return source

if __name__ == '__main__':
    print('Authenticated MIR dependency:', scopeguard(), SCOPEGUARD_SHA256)
