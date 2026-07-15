import subprocess
import unittest
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BINARY = ROOT / "build" / "new_sort"


def ascii_fold(record):
    return bytes(value - 32 if 97 <= value <= 122 else value for value in record)


def expected_output(records, ignore_case=True, reverse=False):
    if ignore_case:
        ordered = sorted(records, key=lambda record: (ascii_fold(record), record), reverse=reverse)
    else:
        ordered = sorted(records, reverse=reverse)
    return b"".join(record + b"\n" for record in ordered)


class NewSortIgnoreCaseTests(unittest.TestCase):
    def run_sort(self, input_data, *arguments):
        return subprocess.run(
            [str(BINARY), *arguments],
            input=input_data,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def assert_sorted(
        self, input_data, records, *arguments, ignore_case=True, reverse=False
    ):
        result = self.run_sort(input_data, *arguments)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            result.stdout,
            expected_output(records, ignore_case=ignore_case, reverse=reverse),
        )
        self.assertEqual(result.stderr, b"")
        if records:
            self.assertTrue(result.stdout.endswith(b"\n"))
        else:
            self.assertEqual(result.stdout, b"")

    def assert_ignore_case_sorted(self, input_data, records, *arguments, reverse=False):
        if not arguments:
            arguments = ("-f",)
        self.assert_sorted(
            input_data,
            records,
            *arguments,
            ignore_case=True,
            reverse=reverse,
        )

    def assert_equivalent_forms(self, input_data, records, forms, reverse=False):
        expected = expected_output(records, ignore_case=True, reverse=reverse)
        outputs = []
        for arguments in forms:
            result = self.run_sort(input_data, *arguments)
            self.assertEqual(result.returncode, 0, arguments)
            self.assertEqual(result.stdout, expected, arguments)
            self.assertEqual(result.stderr, b"", arguments)
            outputs.append(result.stdout)
        self.assertTrue(all(output == outputs[0] for output in outputs))

    def assert_invalid_arguments(self, *arguments):
        result = self.run_sort(b"Visible Input\n", *arguments)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        self.assertIn(b"usage", result.stderr.lower())

    def test_short_ignore_case_uses_ascii_folded_primary_order(self):
        records = [b"pear", b"Apple", b"banana", b"apricot"]
        self.assert_ignore_case_sorted(b"\n".join(records) + b"\n", records, "-f")

    def test_long_ignore_case_matches_short_form(self):
        records = [b"Z", b"alpha", b"Middle", b"ALPHA", b"\xff"]
        input_data = b"\n".join(records) + b"\n"
        self.assert_equivalent_forms(
            input_data, records, [("-f",), ("--ignore-case",)]
        )

    def test_no_option_remains_normal_bytewise_sorting(self):
        records = [b"a", b"B", b"A", b"b"]
        self.assert_sorted(
            b"\n".join(records) + b"\n",
            records,
            ignore_case=False,
        )

    def test_lowercase_input(self):
        records = [b"zulu", b"alpha", b"middle"]
        self.assert_ignore_case_sorted(b"\n".join(records) + b"\n", records)

    def test_uppercase_input(self):
        records = [b"ZULU", b"ALPHA", b"MIDDLE"]
        self.assert_ignore_case_sorted(b"\n".join(records) + b"\n", records)

    def test_mixed_case_input(self):
        records = [b"zULu", b"Alpha", b"mIDdle", b"BRAVO"]
        self.assert_ignore_case_sorted(b"\n".join(records) + b"\n", records)

    def test_three_or_more_case_variants_use_original_byte_secondary_order(self):
        records = [b"apple", b"aPPLE", b"Apple", b"APPLE", b"ApPlE"]
        self.assert_ignore_case_sorted(b"\n".join(records) + b"\n", records)

    def test_ascii_folding_changes_order_when_primary_keys_differ(self):
        records = [b"a", b"B", b"c", b"D"]
        input_data = b"\n".join(records) + b"\n"
        normal = self.run_sort(input_data)
        folded = self.run_sort(input_data, "-f")
        self.assertEqual(normal.returncode, 0)
        self.assertEqual(normal.stderr, b"")
        self.assertEqual(folded.returncode, 0)
        self.assertEqual(folded.stderr, b"")
        self.assertEqual(normal.stdout, expected_output(records, ignore_case=False))
        self.assertEqual(folded.stdout, expected_output(records))
        self.assertNotEqual(normal.stdout, folded.stdout)

    def test_ascii_folding_can_leave_order_unchanged(self):
        records = [b"charlie", b"alpha", b"bravo", b"123", b"!mark"]
        input_data = b"\n".join(records) + b"\n"
        expected = expected_output(records, ignore_case=False)
        self.assertEqual(expected_output(records), expected)
        self.assert_ignore_case_sorted(input_data, records)

    def test_prefix_relationships_after_case_folding(self):
        records = [b"ab", b"AA", b"a", b"AaA", b"ABCD"]
        self.assert_ignore_case_sorted(b"\n".join(records) + b"\n", records)

    def test_empty_input(self):
        self.assert_ignore_case_sorted(b"", [])

    def test_one_empty_record(self):
        self.assert_ignore_case_sorted(b"\n", [b""])

    def test_one_nonempty_record(self):
        self.assert_ignore_case_sorted(b"Only\n", [b"Only"])

    def test_multiple_empty_records(self):
        self.assert_ignore_case_sorted(b"\n\n\n", [b"", b"", b""])

    def test_empty_and_nonempty_records_together(self):
        records = [b"", b"Word", b"", b"z"]
        self.assert_ignore_case_sorted(b"\nWord\n\nz\n", records)

    def test_byte_identical_duplicates(self):
        records = [b"Dog", b"Dog", b"cat", b"Dog"]
        self.assert_ignore_case_sorted(b"\n".join(records) + b"\n", records)

    def test_case_equivalent_but_byte_different_records(self):
        records = [b"same", b"SAME", b"Same", b"sAME"]
        self.assert_ignore_case_sorted(b"\n".join(records) + b"\n", records)

    def test_multiple_nonadjacent_case_equivalent_groups(self):
        records = [b"beta", b"ALPHA", b"Beta", b"gamma", b"alpha", b"BETA"]
        self.assert_ignore_case_sorted(b"\n".join(records) + b"\n", records)

    def test_digits_and_punctuation(self):
        records = [b"item-10", b"Item-2", b"!Alpha", b"[alpha", b"item_1", b"0"]
        self.assert_ignore_case_sorted(b"\n".join(records) + b"\n", records)

    def test_leading_and_trailing_spaces(self):
        records = [b" Alpha", b"alpha", b"Beta ", b"beta", b" ALPHA"]
        self.assert_ignore_case_sorted(b"\n".join(records) + b"\n", records)

    def test_tabs_and_non_newline_control_bytes(self):
        records = [b"A\tb", b"a\tB", b"A\rb", b"a\x01B", b"\x7f", b"\t"]
        self.assert_ignore_case_sorted(b"\n".join(records) + b"\n", records)

    def test_embedded_nul_bytes(self):
        records = [b"A\x00b", b"a", b"a\x00A", b"\x00", b"a\x00"]
        self.assert_ignore_case_sorted(b"\n".join(records) + b"\n", records)

    def test_multiple_embedded_nul_bytes(self):
        records = [b"X\x00\x00z", b"x\x00\x00A", b"\x00\x00", b"x\x00Y\x00"]
        self.assert_ignore_case_sorted(b"\n".join(records) + b"\n", records)

    def test_non_ascii_bytes_remain_unchanged(self):
        records = [b"\xff", b"\x80", b"\x7f", b"\xfe", b"\x81"]
        self.assert_ignore_case_sorted(b"\n".join(records) + b"\n", records)

    def test_mixed_ascii_and_non_ascii_bytes(self):
        records = [b"A\xff", b"a\x80", b"ASCII", b"\x80a", b"z\xff", b"Z"]
        self.assert_ignore_case_sorted(b"\n".join(records) + b"\n", records)

    def test_final_record_without_newline(self):
        records = [b"Beta", b"alpha"]
        self.assert_ignore_case_sorted(b"Beta\nalpha", records)

    def test_one_byte_final_record_without_newline(self):
        self.assert_ignore_case_sorted(b"x", [b"x"])

    def test_records_longer_than_four_kib_are_not_truncated(self):
        long_record = b"x" * 20000
        records = [long_record, b"Short", b"X" * 5000]
        self.assert_ignore_case_sorted(b"\n".join(records) + b"\n", records)

    def test_records_with_long_common_folded_prefixes(self):
        prefix_upper = b"P" * 10000
        prefix_lower = b"p" * 10000
        records = [prefix_lower + b"c", prefix_upper + b"A", prefix_lower, prefix_upper + b"b"]
        self.assert_ignore_case_sorted(b"\n".join(records) + b"\n", records)

    def test_large_number_of_mixed_case_records(self):
        records = []
        for index in range(3000, -1, -1):
            prefix = b"Item-" if index % 2 else b"iTEM-"
            records.append(prefix + f"{index:05d}".encode("ascii"))
        self.assert_ignore_case_sorted(b"\n".join(records) + b"\n", records)

    def test_large_number_of_case_equivalent_groups(self):
        records = []
        for index in range(1000, -1, -1):
            suffix = f"{index:04d}".encode("ascii")
            records.extend([b"item-" + suffix, b"ITEM-" + suffix, b"ItEm-" + suffix])
        self.assert_ignore_case_sorted(b"\n".join(records) + b"\n", records)

    def test_input_records_are_not_modified(self):
        records = [b"\x00Keep\xff ", b"\tUnchanged\r", b" Leading And Trailing "]
        self.assert_ignore_case_sorted(b"\n".join(records) + b"\n", records)

    def test_every_input_record_appears_exactly_once(self):
        records = [b"Z", b"a", b"z", b"B", b"A", b"z", b""]
        result = self.run_sort(b"\n".join(records) + b"\n", "-f")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, b"")
        self.assertTrue(result.stdout.endswith(b"\n"))
        output_records = result.stdout[:-1].split(b"\n")
        self.assertEqual(Counter(output_records), Counter(records))
        self.assertEqual(
            output_records,
            sorted(records, key=lambda record: (ascii_fold(record), record)),
        )

    def test_combined_short_option_orders_are_equivalent(self):
        records = [b"a", b"B", b"A", b"b", b"z"]
        input_data = b"\n".join(records) + b"\n"
        self.assert_equivalent_forms(
            input_data, records, [("-rf",), ("-fr",)], reverse=True
        )

    def test_separate_short_option_orders_are_equivalent(self):
        records = [b"a", b"B", b"A", b"b", b"z"]
        input_data = b"\n".join(records) + b"\n"
        self.assert_equivalent_forms(
            input_data, records, [("-r", "-f"), ("-f", "-r")], reverse=True
        )

    def test_short_and_long_option_combinations_are_equivalent(self):
        records = [b"a", b"B", b"A", b"b", b"z"]
        input_data = b"\n".join(records) + b"\n"
        self.assert_equivalent_forms(
            input_data,
            records,
            [("-rf",), ("--reverse", "--ignore-case")],
            reverse=True,
        )

    def test_mixed_short_and_long_option_combinations_are_equivalent(self):
        records = [b"a", b"B", b"A", b"b", b"z"]
        input_data = b"\n".join(records) + b"\n"
        self.assert_equivalent_forms(
            input_data,
            records,
            [("-r", "--ignore-case"), ("--reverse", "-f")],
            reverse=True,
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

    def test_ignore_case_with_value_fails(self):
        self.assert_invalid_arguments("--ignore-case=value")

    def test_multiple_invalid_arguments_fail(self):
        self.assert_invalid_arguments("-f", "-x", "operand", "--unknown")

    def test_repeated_executions_do_not_share_process_state(self):
        cases = [
            ([b"Z", b"a"], b"Z\na\n", ("-f",), True, False),
            ([b"Z", b"a"], b"Z\na\n", (), False, False),
            ([], b"", ("--ignore-case",), True, False),
            ([b"B", b"a", b"A"], b"B\na\nA\n", ("-rf",), True, True),
        ]
        for records, input_data, arguments, ignore_case, reverse in cases:
            with self.subTest(records=records, arguments=arguments):
                self.assert_sorted(
                    input_data,
                    records,
                    *arguments,
                    ignore_case=ignore_case,
                    reverse=reverse,
                )


if __name__ == "__main__":
    unittest.main()
