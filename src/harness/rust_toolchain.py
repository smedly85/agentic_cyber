"""Check the actual host compiler/linker/runtime before spending agent budget."""

import json
import subprocess
import sys
import tempfile
from pathlib import Path


def main():
    compiler = sys.argv[1]
    try:
        version = subprocess.run(
            [compiler, "--version"], check=True, capture_output=True, text=True,
            timeout=30,
        ).stdout.strip()
        if not version:
            raise ValueError("rustc --version returned an empty version")
        with tempfile.TemporaryDirectory(prefix="rust-preflight-") as directory:
            source = Path(directory) / "probe.rs"
            executable = Path(directory) / "probe"
            source.write_text('fn main() { println!("rust-toolchain-ready"); }\n')
            subprocess.run(
                [compiler, "--edition=2021", "-D", "warnings", str(source),
                 "-o", str(executable)],
                check=True, capture_output=True, text=True, timeout=60,
            )
            result = subprocess.run(
                [str(executable)], check=True, capture_output=True, text=True,
                timeout=10,
            )
            if result.stdout.strip() != "rust-toolchain-ready":
                raise ValueError("Rust probe returned unexpected output")
        # Do not resolve the rustup symlink: its rustc invocation name matters.
        print(json.dumps({"compiler_path": compiler, "version": version,
                          "edition": "2021", "compile_execute_verified": True}))
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        detail = getattr(error, "stderr", None) or str(error)
        if isinstance(detail, bytes):
            detail = detail.decode(errors="replace")
        print(f"infrastructure_error: rust_toolchain_unavailable: {compiler}: {detail}",
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
