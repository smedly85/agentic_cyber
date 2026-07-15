import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BINARY = ROOT / "build" / "new_sort"


def expected_output(lines):
    return b"".join(line + b"\n" for line in sorted(lines))


class NewSortTests(unittest.TestCase):
    def run_sort(self, input_data, *arguments):
        return subprocess.run(
            [str(BINARY), *arguments],
            input=input_data,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def assert_sorted(self, input_data, lines):
        result = self.run_sort(input_data)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, expected_output(lines))
        self.assertEqual(result.stderr, b"")

    def test_basic_unsorted_input(self):
        lines = [b"pear", b"apple", b"banana"]
        self.assert_sorted(b"\n".join(lines) + b"\n", lines)

    def test_already_sorted_input(self):
        lines = [b"alpha", b"beta", b"gamma"]
        self.assert_sorted(b"\n".join(lines) + b"\n", lines)

    def test_reverse_ordered_input(self):
        lines = [b"zebra", b"middle", b"aardvark"]
        self.assert_sorted(b"\n".join(lines) + b"\n", lines)

    def test_empty_input(self):
        self.assert_sorted(b"", [])

    def test_single_line(self):
        self.assert_sorted(b"only\n", [b"only"])

    def test_empty_lines(self):
        lines = [b"", b"word", b""]
        self.assert_sorted(b"\nword\n\n", lines)

    def test_duplicate_lines(self):
        lines = [b"dog", b"dog", b"cat", b"dog"]
        self.assert_sorted(b"\n".join(lines) + b"\n", lines)

    def test_lines_containing_spaces(self):
        lines = [b"two words", b" leading", b"trailing ", b"a b"]
        self.assert_sorted(b"\n".join(lines) + b"\n", lines)

    def test_prefix_relationships(self):
        lines = [b"ab", b"aa", b"a", b"aaa"]
        self.assert_sorted(b"\n".join(lines) + b"\n", lines)

    def test_ascii_character_order(self):
        lines = [b"lower", b"Upper", b"!mark", b"[bracket", b"Zed", b"apple"]
        self.assert_sorted(b"\n".join(lines) + b"\n", lines)

    def test_final_line_without_newline(self):
        lines = [b"beta", b"alpha"]
        self.assert_sorted(b"beta\nalpha", lines)

    def test_line_longer_than_four_kib(self):
        long_line = b"x" * 20000
        lines = [long_line, b"short", b"x" * 5000]
        self.assert_sorted(b"\n".join(lines) + b"\n", lines)

    def test_large_number_of_lines(self):
        lines = [f"record-{index:05d}".encode("ascii") for index in range(4999, -1, -1)]
        lines.extend([b"record-00010", b"record-00010"])
        self.assert_sorted(b"\n".join(lines) + b"\n", lines)

    def test_unexpected_argument(self):
        result = self.run_sort(b"input that must not be read\n", "anything")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        self.assertIn(b"usage", result.stderr.lower())

    def test_output_error(self):
        with open("/dev/full", "wb") as full_device:
            result = subprocess.run(
                [str(BINARY)],
                input=b"line\n",
                stdout=full_device,
                stderr=subprocess.PIPE,
                check=False,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"output error", result.stderr.lower())


if __name__ == "__main__":
    unittest.main()
