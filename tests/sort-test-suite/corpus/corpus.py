#!/usr/bin/env python3
"""
Deterministic input corpus for the exhaustive sort suite.

Two families:
  CORE   - small, hand-crafted files engineered so that comparators actually
           discriminate (every sort mode orders `discrim` differently), and
           so ties/dups/blank-handling are exercised. Returned as bytes.
  ADVERSARIAL - stress/robustness inputs (huge lines, NUL bytes, invalid
           UTF-8, missing trailing newline, ...). Seeded where random.

All values are bytes. build_core()/build_adversarial() return name->bytes.

The discrimination assertion (assert_discriminating) runs GNU sort on the
`discrim` file under every ordering mode and requires the outputs to be
pairwise-distinct; the generator calls it and aborts if any pair collides,
so the corpus is provably able to tell the modes apart.
"""
from __future__ import annotations

import random
import subprocess

TAB = b"\t"


def _lines(*rows: bytes) -> bytes:
    return b"".join(r + b"\n" for r in rows)


def build_core() -> dict[str, bytes]:
    c: dict[str, bytes] = {}

    # Engineered so default / -n / -g / -h / -V / -M / -f / -d / -i / -b / -r
    # all produce different orderings. Mixes numeric, human, version, month,
    # hex(general), signed/zero, punctuation, case, and leading blanks.
    # The a\x7fa / aza pair reorders ONLY under -i (DEL is nonprinting, so -i
    # ignores it): default sorts by byte (0x7f > 'z'), -i compares "aa" < "aza".
    c["discrim"] = _lines(
        b" 10K", b"9M", b"2.5", b"1e2", b"0x1A", b"-0", b"0", b"1,000",
        b".5", b"JAN 5", b"feb 3", b"v1.10", b"v1.9", b"10", b"2", b"1G",
        b"3K", b"abc", b"ABC", b"  abc", b"a-b", b"a b", b"#3", b"1.0.1",
        b"a\x7fa", b"aza",
    )

    # repeated equal keys with differing full lines -> -s / -u / last-resort
    c["ties"] = _lines(b"1 z", b"1 a", b"01 m", b"+1 b", b"1 a", b"2 q")

    # columnar, mixed separators, leading blanks, empty fields, short rows
    c["fields"] = _lines(
        b"c\tb\ta", b"a\tz\tm", b"a\tb\tc", b"  a\tb\tc", b"a::c",
        b"b\tb", b"a\tb\tc\td",
    )

    # numeric / general / human edge cases
    c["numbers"] = _lines(
        b"", b"-0", b"+1", b"1e1", b"inf", b"-inf", b"nan",
        b"0.00000001", b"9" * 30, b"1,234", b"1K", b"1k", b"1Ki", b"2%",
        b"-5", b"100", b"3.14",
    )

    c["months"] = _lines(
        b"JAN", b"feb", b"Mar", b"APR", b"may", b"Jun", b"JUL", b"aug",
        b"SEP", b"oct", b"Nov", b"DEC", b"jAn", b"Janx", b"foo", b"  MAR",
    )

    c["versions"] = _lines(
        b"a1", b"a10", b"a2", b"1.2.3~rc1", b"1.2.3", b"1.2.3-4", b"..",
        b"v1.9", b"v1.10", b"file-2.0", b"file-10.0",
    )

    c["generic"] = _lines(*(
        [b"apple", b"Apple", b"banana", b"cherry", b"apple", b"date",
         b"Banana", b"fig", b"grape", b"kiwi", b"lemon", b"mango",
         b"apple", b"nectarine", b"orange", b"pear", b"quince", b"kiwi",
         b"raspberry", b"strawberry", b"tangerine", b"ugli", b"vanilla",
         b"watermelon", b"xigua", b"yam", b"zucchini", b"date", b"fig",
         b"lemon"]))

    c["presorted"] = _lines(b"a", b"b", b"c", b"d", b"e")
    c["reverse_sorted"] = _lines(b"e", b"d", b"c", b"b", b"a")
    c["almost_sorted"] = _lines(b"a", b"b", b"d", b"c", b"e")

    # presorted (default C order) inputs for -m
    c["merge_a"] = _lines(b"a", b"d", b"g", b"j")
    c["merge_b"] = _lines(b"b", b"e", b"h", b"k")
    c["merge_c"] = _lines(b"c", b"f", b"i", b"l")

    # NUL-terminated records (for -z); records deliberately contain newlines
    c["zrecords"] = b"b\nb\x00a\x00a\nc\x00"

    return c


def build_adversarial(seed: int = 1) -> dict[str, bytes]:
    rng = random.Random(seed)
    a: dict[str, bytes] = {}

    a["empty"] = b""
    a["blanks_only"] = _lines(b"", b"", b"", b"")
    a["nonewline"] = b"b\na"                       # no trailing newline
    a["nulbytes"] = b"foo\x00bar\nbaz\x00qux\n"    # NUL mid-line (non -z)
    a["badutf8"] = b"\xff\xfe\nvalid\n\xc3\x28\n"  # invalid UTF-8 sequences
    a["crlf"] = b"b\r\na\r\n"                       # CR treated as data
    a["one_field_short"] = _lines(b"a", b"a\tb\tc", b"", b"a\tb")

    # 8 MiB single line + a couple normal lines
    huge = b"x" * (8 * 1024 * 1024)
    a["hugeline"] = huge + b"\nshort\naaa\n"

    # many short lines -> with -S 32b this forces external merge
    lines = []
    for _ in range(200_000):
        lines.append(str(rng.randint(0, 1_000_000)).encode())
    a["manylines"] = b"\n".join(lines) + b"\n"

    # a line with 10k fields
    a["widefield"] = b"\t".join(str(i).encode() for i in range(10_000)) + b"\n"

    return a


# --- discrimination assertion ------------------------------------------------

DISCRIM_MODES = [
    ("default", []), ("-n", ["-n"]), ("-g", ["-g"]), ("-h", ["-h"]),
    ("-V", ["-V"]), ("-M", ["-M"]), ("-f", ["-f"]), ("-d", ["-d"]),
    ("-i", ["-i"]), ("-b", ["-b"]), ("-r", ["-r"]),
]


def _gnu_sort(data: bytes, args: list[str], sort_bin: str) -> bytes:
    p = subprocess.run([sort_bin] + args, input=data,
                       capture_output=True,
                       env={"LC_ALL": "C", "LANG": "C", "LANGUAGE": "C",
                            "PATH": "/usr/bin:/bin"})
    return p.stdout


def assert_discriminating(sort_bin: str = "/usr/bin/sort") -> None:
    """Run GNU sort on `discrim` under every mode; require pairwise-distinct
    outputs. Also require -s to differ from default on `ties`. Raises
    AssertionError naming the colliding pair if the corpus fails to
    discriminate (a corpus bug, not a candidate bug)."""
    discrim = build_core()["discrim"]
    outs = {name: _gnu_sort(discrim, args, sort_bin)
            for name, args in DISCRIM_MODES}
    names = list(outs)
    collisions = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            if outs[names[i]] == outs[names[j]]:
                collisions.append((names[i], names[j]))
    if collisions:
        raise AssertionError(
            "corpus 'discrim' fails to discriminate these mode pairs "
            f"(they produce identical output): {collisions}")

    ties = build_core()["ties"]
    if _gnu_sort(ties, [], sort_bin) == _gnu_sort(ties, ["-s"], sort_bin):
        # default vs -s can legitimately match on some inputs; ensure our
        # ties file actually exposes the difference via a key.
        d = _gnu_sort(ties, ["-k1,1"], sort_bin)
        s = _gnu_sort(ties, ["-k1,1", "-s"], sort_bin)
        if d == s:
            raise AssertionError(
                "corpus 'ties' fails to distinguish -s from default")


if __name__ == "__main__":
    assert_discriminating()
    core = build_core()
    print("core inputs:", ", ".join(f"{k}({len(v)}B)" for k, v in core.items()))
    print("discrimination assertion: PASS")
