import subprocess
import unittest
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BINARY = ROOT / "build" / "new_sort"


def expected_output(records, reverse=False):
    return b"".join(record + b"\n" for record in sorted(records, reverse=reverse))


class NewSortReverseTests(unittest.TestCase):
    def run_sort(self, input_data, *arguments):
        return subprocess.run(
            [str(BINARY), *arguments],
            input=input_data,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def assert_sorted(self, input_data, records, *arguments, reverse=True):
        result = self.run_sort(input_data, *arguments)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, expected_output(records, reverse=reverse))
        self.assertEqual(result.stderr, b"")
        if records:
            self.assertTrue(result.stdout.endswith(b"\n"))
        else:
            self.assertEqual(result.stdout, b"")

    def assert_reverse_sorted(self, input_data, records, *arguments):
        if not arguments:
            arguments = ("-r",)
        self.assert_sorted(input_data, records, *arguments, reverse=True)

    def assert_invalid_arguments(self, *arguments):
        result = self.run_sort(b"visible input\n", *arguments)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        self.assertIn(b"usage", result.stderr.lower())

    def test_short_reverse_produces_descending_bytewise_order(self):
        records = [b"pear", b"apple", b"banana", b"apricot"]
        self.assert_reverse_sorted(b"\n".join(records) + b"\n", records, "-r")

    def test_long_reverse_matches_short_reverse(self):
        records = [b"z", b"alpha", b"middle", b"alpha", b"\xff"]
        input_data = b"\n".join(records) + b"\n"
        short_result = self.run_sort(input_data, "-r")
        long_result = self.run_sort(input_data, "--reverse")
        self.assertEqual(short_result.returncode, 0)
        self.assertEqual(long_result.returncode, 0)
        self.assertEqual(short_result.stdout, expected_output(records, reverse=True))
        self.assertEqual(long_result.stdout, short_result.stdout)
        self.assertEqual(short_result.stderr, b"")
        self.assertEqual(long_result.stderr, b"")

    def test_no_option_remains_ascending(self):
        records = [b"pear", b"apple", b"banana"]
        self.assert_sorted(
            b"\n".join(records) + b"\n", records, reverse=False
        )

    def test_already_ascending_input(self):
        records = [b"alpha", b"beta", b"gamma"]
        self.assert_reverse_sorted(b"\n".join(records) + b"\n", records)

    def test_already_descending_input(self):
        records = [b"zebra", b"middle", b"aardvark"]
        self.assert_reverse_sorted(b"\n".join(records) + b"\n", records)

    def test_unordered_input(self):
        records = [b"delta", b"alpha", b"charlie", b"bravo"]
        self.assert_reverse_sorted(b"\n".join(records) + b"\n", records)

    def test_empty_input(self):
        self.assert_reverse_sorted(b"", [])

    def test_one_empty_record(self):
        self.assert_reverse_sorted(b"\n", [b""])

    def test_one_nonempty_record(self):
        self.assert_reverse_sorted(b"only\n", [b"only"])

    def test_multiple_empty_records(self):
        self.assert_reverse_sorted(b"\n\n\n", [b"", b"", b""])

    def test_empty_records_mixed_with_nonempty_records(self):
        records = [b"", b"word", b"", b"z"]
        self.assert_reverse_sorted(b"\nword\n\nz\n", records)

    def test_duplicate_records(self):
        records = [b"dog", b"dog", b"cat", b"dog"]
        self.assert_reverse_sorted(b"\n".join(records) + b"\n", records)

    def test_multiple_duplicate_groups_and_nonadjacent_duplicates(self):
        records = [b"beta", b"alpha", b"gamma", b"beta", b"alpha", b"beta"]
        self.assert_reverse_sorted(b"\n".join(records) + b"\n", records)

    def test_prefixes_put_longer_records_first(self):
        records = [b"ab", b"aa", b"a", b"aaa"]
        self.assert_reverse_sorted(b"\n".join(records) + b"\n", records)

    def test_leading_and_trailing_spaces(self):
        records = [b" leading", b"leading", b"trailing ", b"trailing", b"a b"]
        self.assert_reverse_sorted(b"\n".join(records) + b"\n", records)

    def test_records_containing_only_spaces(self):
        records = [b"   ", b" ", b"  ", b""]
        self.assert_reverse_sorted(b"\n".join(records) + b"\n", records)

    def test_tabs_and_non_newline_control_bytes(self):
        records = [b"a\tb", b"a\rb", b"a\x01b", b"\x7f", b"\t"]
        self.assert_reverse_sorted(b"\n".join(records) + b"\n", records)

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
        self.assert_reverse_sorted(b"\n".join(records) + b"\n", records)

    def test_embedded_nul_bytes(self):
        records = [b"a\x00b", b"a", b"a\x00a", b"\x00", b"a\x00"]
        self.assert_reverse_sorted(b"\n".join(records) + b"\n", records)

    def test_multiple_embedded_nul_bytes(self):
        records = [b"x\x00\x00z", b"x\x00\x00a", b"\x00\x00", b"x\x00y\x00"]
        self.assert_reverse_sorted(b"\n".join(records) + b"\n", records)

    def test_unsigned_bytes_above_ascii(self):
        records = [b"\xff", b"\x80", b"\x7f", b"\xfe", b"\x81"]
        self.assert_reverse_sorted(b"\n".join(records) + b"\n", records)

    def test_mixed_ascii_and_non_ascii_bytes(self):
        records = [b"a\xff", b"a\x80", b"ascii", b"\x80a", b"z\xff", b"z"]
        self.assert_reverse_sorted(b"\n".join(records) + b"\n", records)

    def test_final_record_without_newline(self):
        records = [b"beta", b"alpha"]
        self.assert_reverse_sorted(b"beta\nalpha", records)

    def test_one_byte_final_record_without_newline(self):
        self.assert_reverse_sorted(b"x", [b"x"])

    def test_records_longer_than_four_kib_are_not_truncated(self):
        long_record = b"x" * 20000
        records = [long_record, b"short", b"x" * 5000]
        self.assert_reverse_sorted(b"\n".join(records) + b"\n", records)

    def test_records_with_long_common_prefixes(self):
        prefix = b"p" * 10000
        records = [prefix + b"c", prefix + b"a", prefix, prefix + b"b"]
        self.assert_reverse_sorted(b"\n".join(records) + b"\n", records)

    def test_large_number_of_records(self):
        records = [f"record-{index:05d}".encode("ascii") for index in range(5000)]
        self.assert_reverse_sorted(b"\n".join(records) + b"\n", records)

    def test_large_number_of_duplicate_records(self):
        records = [b"same"] * 3000 + [b"other"] * 2000 + [b"last"] * 1000
        self.assert_reverse_sorted(b"\n".join(records) + b"\n", records)

    def test_input_records_are_not_modified(self):
        records = [b"\x00keep\xff ", b"\tunchanged\r", b" leading and trailing "]
        self.assert_reverse_sorted(b"\n".join(records) + b"\n", records)

    def test_every_input_record_appears_exactly_once(self):
        records = [b"z", b"a", b"z", b"b", b"a", b"z", b""]
        result = self.run_sort(b"\n".join(records) + b"\n", "-r")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, b"")
        self.assertTrue(result.stdout.endswith(b"\n"))
        output_records = result.stdout[:-1].split(b"\n")
        self.assertEqual(Counter(output_records), Counter(records))
        self.assertEqual(output_records, sorted(records, reverse=True))

    def test_repeated_short_reverse_is_idempotent(self):
        records = [b"c", b"a", b"b"]
        input_data = b"c\na\nb\n"
        self.assert_reverse_sorted(input_data, records, "-r", "-r")

    def test_clustered_short_reverse_is_idempotent(self):
        records = [b"c", b"a", b"b"]
        input_data = b"c\na\nb\n"
        self.assert_reverse_sorted(input_data, records, "-rr")

    def test_repeated_long_reverse_is_idempotent(self):
        records = [b"c", b"a", b"b"]
        input_data = b"c\na\nb\n"
        self.assert_reverse_sorted(input_data, records, "--reverse", "--reverse")

    def test_mixed_repeated_reverse_forms_are_idempotent(self):
        records = [b"c", b"a", b"b"]
        input_data = b"c\na\nb\n"
        self.assert_reverse_sorted(
            input_data, records, "-r", "--reverse", "-rr", "--reverse"
        )

    def test_unknown_short_option_fails(self):
        self.assert_invalid_arguments("-x")

    def test_unknown_long_option_fails(self):
        self.assert_invalid_arguments("--unknown")

    def test_non_option_operand_fails(self):
        self.assert_invalid_arguments("operand")

    def test_single_dash_is_rejected(self):
        self.assert_invalid_arguments("-")

    def test_double_dash_is_rejected(self):
        self.assert_invalid_arguments("--")

    def test_reverse_with_value_fails(self):
        self.assert_invalid_arguments("--reverse=value")

    def test_multiple_invalid_arguments_fail(self):
        self.assert_invalid_arguments("-r", "-x", "operand", "--unknown")

    def test_repeated_executions_do_not_share_process_state(self):
        cases = [
            ([b"z", b"a"], b"z\na\n", ("-r",), True),
            ([b"z", b"a"], b"z\na\n", (), False),
            ([], b"", ("--reverse",), True),
            ([b"second", b"run", b"run"], b"second\nrun\nrun\n", ("-rr",), True),
        ]
        for records, input_data, arguments, reverse in cases:
            with self.subTest(records=records, arguments=arguments):
                self.assert_sorted(
                    input_data, records, *arguments, reverse=reverse
                )


if __name__ == "__main__":
    unittest.main()
