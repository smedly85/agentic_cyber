"""Controller-only Linux freeze; never staged for an agent."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from linux_benchmark import main
if __name__ == "__main__":
    raise SystemExit(main(["freeze", "--utility", "c-sort", *sys.argv[1:]]))
