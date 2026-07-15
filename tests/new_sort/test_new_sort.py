import subprocess
import unittest
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BINARY = ROOT / "build" / "new_sort"


def expected_output(records):
    return b"".join(record + b"\n" for record in sorted(records))


class NewSortTests(unittest.TestCase):
    def run_sort(self, input_data, *arguments):
        return subprocess.run(
            [str(BINARY), *arguments],
            input=input_data,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def assert_sorted(self, input_data, records):
        result = self.run_sort(input_data)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, expected_output(records))
        self.assertEqual(result.stderr, b"")
        if records:
            self.assertTrue(result.stdout.endswith(b"\n"))
        else:
            self.assertEqual(result.stdout, b"")

    def assert_invalid_arguments(self, *arguments):
        result = self.run_sort(b"visible input\n", *arguments)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        self.assertIn(b"usage", result.stderr.lower())

    def test_basic_unordered_input(self):
        records = [b"pear", b"apple", b"banana"]
        self.assert_sorted(b"\n".join(records) + b"\n", records)

    def test_already_sorted_input(self):
        records = [b"alpha", b"beta", b"gamma"]
        self.assert_sorted(b"\n".join(records) + b"\n", records)

    def test_reverse_ordered_input(self):
        records = [b"zebra", b"middle", b"aardvark"]
        self.assert_sorted(b"\n".join(records) + b"\n", records)

    def test_empty_input(self):
        self.assert_sorted(b"", [])

    def test_one_empty_record(self):
        self.assert_sorted(b"\n", [b""])

    def test_one_nonempty_record(self):
        self.assert_sorted(b"only\n", [b"only"])

    def test_multiple_empty_records(self):
        self.assert_sorted(b"\n\n\n", [b"", b"", b""])

    def test_empty_records_mixed_with_nonempty_records(self):
        records = [b"word", b"", b"z", b""]
        self.assert_sorted(b"word\n\nz\n\n", records)

    def test_duplicate_records(self):
        records = [b"dog", b"dog", b"cat", b"dog"]
        self.assert_sorted(b"\n".join(records) + b"\n", records)

    def test_multiple_duplicate_groups_and_nonadjacent_duplicates(self):
        records = [b"beta", b"alpha", b"gamma", b"beta", b"alpha", b"beta"]
        self.assert_sorted(b"\n".join(records) + b"\n", records)

    def test_ordinary_leading_and_trailing_spaces(self):
        records = [b"two words", b" leading", b"trailing ", b"a b", b"plain"]
        self.assert_sorted(b"\n".join(records) + b"\n", records)

    def test_records_containing_only_spaces(self):
        records = [b"   ", b" ", b"  ", b""]
        self.assert_sorted(b"\n".join(records) + b"\n", records)

    def test_tabs_and_non_newline_control_bytes(self):
        records = [b"a\tb", b"a\rb", b"a\x01b", b"\x7f", b"\t"]
        self.assert_sorted(b"\n".join(records) + b"\n", records)

    def test_punctuation_digits_and_ascii_case(self):
        records = [
            b"lower",
            b"Upper",
            b"!mark",
            b"[bracket",
            b"Zed",
            b"apple",
            b"10",
            b"2",
            b"0",
            b"~",
        ]
        self.assert_sorted(b"\n".join(records) + b"\n", records)

    def test_prefix_relationships(self):
        records = [b"ab", b"aa", b"a", b"aaa"]
        self.assert_sorted(b"\n".join(records) + b"\n", records)

    def test_records_differing_only_in_final_byte(self):
        records = [b"common-c", b"common-a", b"common-b", b"common-\xff"]
        self.assert_sorted(b"\n".join(records) + b"\n", records)

    def test_embedded_nul_bytes(self):
        records = [b"a\x00b", b"a", b"a\x00a", b"\x00", b"a\x00"]
        self.assert_sorted(b"\n".join(records) + b"\n", records)

    def test_multiple_embedded_nul_bytes(self):
        records = [b"x\x00\x00z", b"x\x00\x00a", b"\x00\x00", b"x\x00y\x00"]
        self.assert_sorted(b"\n".join(records) + b"\n", records)

    def test_unsigned_bytes_above_ascii(self):
        records = [b"\xff", b"\x80", b"\x7f", b"\xfe", b"\x81"]
        self.assert_sorted(b"\n".join(records) + b"\n", records)

    def test_mixed_ascii_and_non_ascii_bytes(self):
        records = [b"a\xff", b"a\x80", b"ascii", b"\x80a", b"z\xff", b"z"]
        self.assert_sorted(b"\n".join(records) + b"\n", records)

    def test_record_containing_every_byte_except_newline(self):
        all_non_newline_bytes = bytes(value for value in range(256) if value != 10)
        records = [all_non_newline_bytes, b"ordinary"]
        self.assert_sorted(b"\n".join(records) + b"\n", records)

    def test_final_record_without_newline(self):
        records = [b"beta", b"alpha"]
        self.assert_sorted(b"beta\nalpha", records)

    def test_one_byte_final_record_without_newline(self):
        self.assert_sorted(b"x", [b"x"])

    def test_terminating_newline_does_not_add_an_empty_record(self):
        self.assert_sorted(b"alpha\n", [b"alpha"])

    def test_record_longer_than_four_kib_is_not_truncated(self):
        long_record = b"x" * 20000
        records = [long_record, b"short", b"x" * 5000]
        self.assert_sorted(b"\n".join(records) + b"\n", records)

    def test_records_with_different_long_common_prefixes(self):
        prefix = b"p" * 10000
        records = [prefix + b"c", prefix + b"a", prefix, prefix + b"b"]
        self.assert_sorted(b"\n".join(records) + b"\n", records)

    def test_large_number_of_records(self):
        records = [f"record-{index:05d}".encode("ascii") for index in range(4999, -1, -1)]
        self.assert_sorted(b"\n".join(records) + b"\n", records)

    def test_large_number_of_duplicate_records(self):
        records = [b"same"] * 3000 + [b"other"] * 2000 + [b"last"] * 1000
        self.assert_sorted(b"\n".join(records) + b"\n", records)

    def test_input_records_are_not_modified(self):
        records = [b"\x00keep\xff ", b"\tunchanged\r", b" leading and trailing "]
        self.assert_sorted(b"\n".join(records) + b"\n", records)

    def test_every_input_record_appears_exactly_once(self):
        records = [b"z", b"a", b"z", b"b", b"a", b"z", b""]
        result = self.run_sort(b"\n".join(records) + b"\n")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, b"")
        self.assertTrue(result.stdout.endswith(b"\n"))
        output_records = result.stdout[:-1].split(b"\n")
        self.assertEqual(Counter(output_records), Counter(records))
        self.assertEqual(output_records, sorted(records))

    def test_non_option_operand_is_rejected(self):
        self.assert_invalid_arguments("operand")

    def test_multiple_invalid_arguments_are_rejected(self):
        self.assert_invalid_arguments("-x", "operand", "--unknown")

    def test_single_dash_operand_is_rejected(self):
        self.assert_invalid_arguments("-")

    def test_double_dash_argument_is_rejected(self):
        self.assert_invalid_arguments("--")

    def test_output_failure_reports_error(self):
        full_device_path = Path("/dev/full")
        if not full_device_path.exists():
            self.skipTest("/dev/full is unavailable")

        try:
            full_device = full_device_path.open("wb")
        except OSError as error:
            self.skipTest(f"/dev/full cannot be opened: {error}")

        with full_device:
            result = subprocess.run(
                [str(BINARY)],
                input=b"line\n",
                stdout=full_device,
                stderr=subprocess.PIPE,
                check=False,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"output error", result.stderr.lower())

    def test_repeated_execution_has_no_prior_process_state(self):
        cases = [
            ([b"z", b"a"], b"z\na\n"),
            ([], b""),
            ([b"second", b"run", b"run"], b"second\nrun\nrun\n"),
        ]
        for records, input_data in cases:
            with self.subTest(records=records):
                self.assert_sorted(input_data, records)


if __name__ == "__main__":
    unittest.main()
