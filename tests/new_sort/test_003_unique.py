import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BINARY = ROOT / "build" / "new_sort"


def ascii_fold(record):
    return bytes(value - 32 if 97 <= value <= 122 else value for value in record)


def normal_bytewise_order(records):
    return sorted(records)


def ignore_case_order(records):
    return sorted(records, key=lambda record: (ascii_fold(record), record))


def exact_equal(left, right):
    return left == right


def case_insensitive_equal(left, right):
    return ascii_fold(left) == ascii_fold(right)


def equality_groups(records, ignore_case=False):
    if ignore_case:
        ordered = ignore_case_order(records)
        equal = case_insensitive_equal
    else:
        ordered = normal_bytewise_order(records)
        equal = exact_equal

    groups = []
    for record in ordered:
        if not groups or not equal(groups[-1][0], record):
            groups.append([record])
        else:
            groups[-1].append(record)
    return groups


def select_representatives(records, ignore_case=False):
    return [group[0] for group in equality_groups(records, ignore_case)]


def expected_records(records, unique=False, ignore_case=False, reverse=False):
    if unique:
        representatives = select_representatives(records, ignore_case)
        if reverse:
            representatives.reverse()
        return representatives

    if ignore_case:
        ordered = ignore_case_order(records)
    else:
        ordered = normal_bytewise_order(records)
    if reverse:
        ordered.reverse()
    return ordered


def serialize(records):
    return b"".join(record + b"\n" for record in records)


def expected_output(records, unique=False, ignore_case=False, reverse=False):
    return serialize(
        expected_records(
            records,
            unique=unique,
            ignore_case=ignore_case,
            reverse=reverse,
        )
    )


class NewSortUniqueTests(unittest.TestCase):
    def run_sort(self, input_data, *arguments):
        return subprocess.run(
            [str(BINARY), *arguments],
            input=input_data,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def assert_sorted(
        self,
        input_data,
        records,
        *arguments,
        unique=True,
        ignore_case=False,
        reverse=False,
    ):
        result = self.run_sort(input_data, *arguments)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            result.stdout,
            expected_output(
                records,
                unique=unique,
                ignore_case=ignore_case,
                reverse=reverse,
            ),
        )
        self.assertEqual(result.stderr, b"")
        expected = expected_records(
            records,
            unique=unique,
            ignore_case=ignore_case,
            reverse=reverse,
        )
        if expected:
            self.assertTrue(result.stdout.endswith(b"\n"))
        else:
            self.assertEqual(result.stdout, b"")

    def assert_unique_sorted(self, input_data, records, *arguments, **modes):
        if not arguments:
            arguments = ("-u",)
        self.assert_sorted(input_data, records, *arguments, unique=True, **modes)

    def assert_equivalent_forms(
        self, input_data, records, forms, ignore_case=False, reverse=False
    ):
        expected = expected_output(
            records,
            unique=True,
            ignore_case=ignore_case,
            reverse=reverse,
        )
        outputs = []
        for arguments in forms:
            result = self.run_sort(input_data, *arguments)
            self.assertEqual(result.returncode, 0, arguments)
            self.assertEqual(result.stdout, expected, arguments)
            self.assertEqual(result.stderr, b"", arguments)
            outputs.append(result.stdout)
        self.assertTrue(all(output == outputs[0] for output in outputs))

    def assert_invalid_arguments(self, *arguments):
        result = self.run_sort(b"visible\nvisible\ninput\n", *arguments)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        self.assertIn(b"usage", result.stderr.lower())

    def test_short_unique_removes_byte_identical_duplicates(self):
        records = [b"dog", b"dog", b"cat", b"dog"]
        self.assert_unique_sorted(b"\n".join(records) + b"\n", records, "-u")

    def test_long_unique_matches_short_form(self):
        records = [b"z", b"alpha", b"z", b"middle", b"alpha"]
        input_data = b"\n".join(records) + b"\n"
        self.assert_equivalent_forms(input_data, records, [("-u",), ("--unique",)])

    def test_no_option_preserves_duplicates(self):
        records = [b"b", b"a", b"b", b"a"]
        self.assert_sorted(
            b"\n".join(records) + b"\n",
            records,
            unique=False,
        )

    def test_input_without_duplicates(self):
        records = [b"charlie", b"alpha", b"bravo"]
        self.assert_unique_sorted(b"\n".join(records) + b"\n", records)

    def test_input_containing_only_one_repeated_record(self):
        records = [b"same"] * 20
        self.assert_unique_sorted(b"\n".join(records) + b"\n", records)

    def test_nonadjacent_duplicate_groups_of_different_sizes(self):
        records = [b"beta", b"alpha", b"gamma", b"beta", b"alpha", b"beta"]
        self.assert_unique_sorted(b"\n".join(records) + b"\n", records)

    def test_empty_input(self):
        self.assert_unique_sorted(b"", [])

    def test_one_empty_record(self):
        self.assert_unique_sorted(b"\n", [b""])

    def test_multiple_empty_records_collapse_to_one(self):
        self.assert_unique_sorted(b"\n\n\n", [b"", b"", b""])

    def test_empty_records_mixed_with_nonempty_records(self):
        records = [b"", b"word", b"", b"word", b"z"]
        self.assert_unique_sorted(b"\nword\n\nword\nz\n", records)

    def test_prefix_related_records_remain_distinct(self):
        records = [b"a", b"aa", b"aaa", b"a", b"ab"]
        self.assert_unique_sorted(b"\n".join(records) + b"\n", records)

    def test_records_differing_only_in_length_remain_distinct(self):
        records = [b"value", b"value\x00", b"value\x00\x00", b"value"]
        self.assert_unique_sorted(b"\n".join(records) + b"\n", records)

    def test_leading_and_trailing_spaces_remain_significant(self):
        records = [b"value", b" value", b"value ", b" value ", b"value"]
        self.assert_unique_sorted(b"\n".join(records) + b"\n", records)

    def test_tabs_and_spaces_remain_distinct(self):
        records = [b"a b", b"a\tb", b"a  b", b"a\t\tb", b"a b"]
        self.assert_unique_sorted(b"\n".join(records) + b"\n", records)

    def test_case_variants_remain_distinct_without_ignore_case(self):
        records = [b"same", b"SAME", b"Same", b"same"]
        self.assert_unique_sorted(b"\n".join(records) + b"\n", records)

    def test_ignore_case_unique_groups_ascii_case_variants(self):
        records = [b"same", b"SAME", b"Same", b"other"]
        self.assert_unique_sorted(
            b"\n".join(records) + b"\n",
            records,
            "-f",
            "-u",
            ignore_case=True,
        )

    def test_ignore_case_and_unique_option_orders_are_equivalent(self):
        records = [b"same", b"SAME", b"Same", b"other"]
        input_data = b"\n".join(records) + b"\n"
        self.assert_equivalent_forms(
            input_data,
            records,
            [("-u", "-f"), ("-f", "-u")],
            ignore_case=True,
        )

    def test_three_or_more_case_variants_form_one_group(self):
        records = [b"apple", b"aPPLE", b"Apple", b"APPLE", b"ApPlE"]
        self.assert_unique_sorted(
            b"\n".join(records) + b"\n", records, "-fu", ignore_case=True
        )

    def test_deterministic_representative_is_retained(self):
        records = [b"apple", b"Apple", b"APPLE", b"other"]
        result = self.run_sort(b"\n".join(records) + b"\n", "-fu")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b"APPLE\nother\n")
        self.assertEqual(result.stderr, b"")

    def test_input_order_does_not_determine_representative(self):
        first = [b"apple", b"APPLE", b"Apple", b"other"]
        second = [b"Apple", b"other", b"apple", b"APPLE"]
        first_result = self.run_sort(b"\n".join(first) + b"\n", "-fu")
        second_result = self.run_sort(b"\n".join(second) + b"\n", "-fu")
        expected = expected_output(first, unique=True, ignore_case=True)
        self.assertEqual(first_result.returncode, 0)
        self.assertEqual(second_result.returncode, 0)
        self.assertEqual(first_result.stdout, expected)
        self.assertEqual(second_result.stdout, expected)
        self.assertEqual(first_result.stderr, b"")
        self.assertEqual(second_result.stderr, b"")

    def test_reverse_unique_reverses_distinct_exact_groups(self):
        records = [b"beta", b"alpha", b"gamma", b"beta", b"alpha"]
        self.assert_unique_sorted(
            b"\n".join(records) + b"\n", records, "-ru", reverse=True
        )

    def test_reverse_ignore_case_unique_keeps_normal_representative(self):
        records = [b"apple", b"APPLE", b"Apple", b"beta", b"BETA"]
        input_data = b"\n".join(records) + b"\n"
        normal = self.run_sort(input_data, "-fu")
        reverse = self.run_sort(input_data, "-rfu")
        normal_records = expected_records(records, unique=True, ignore_case=True)
        self.assertEqual(normal.returncode, 0)
        self.assertEqual(reverse.returncode, 0)
        self.assertEqual(normal.stdout, serialize(normal_records))
        self.assertEqual(reverse.stdout, serialize(list(reversed(normal_records))))
        self.assertIn(b"APPLE\n", normal.stdout)
        self.assertIn(b"APPLE\n", reverse.stdout)
        self.assertNotIn(b"apple\n", reverse.stdout)
        self.assertEqual(normal.stderr, b"")
        self.assertEqual(reverse.stderr, b"")

    def test_all_three_option_orders_are_equivalent(self):
        records = [b"apple", b"APPLE", b"beta", b"BETA", b"z"]
        input_data = b"\n".join(records) + b"\n"
        forms = [
            ("-r", "-f", "-u"),
            ("-r", "-u", "-f"),
            ("-f", "-r", "-u"),
            ("-f", "-u", "-r"),
            ("-u", "-r", "-f"),
            ("-u", "-f", "-r"),
        ]
        self.assert_equivalent_forms(
            input_data, records, forms, ignore_case=True, reverse=True
        )

    def test_supported_combined_short_forms(self):
        records = [b"apple", b"APPLE", b"beta", b"beta", b"z"]
        input_data = b"\n".join(records) + b"\n"
        cases = [
            (("-fu",), True, False),
            (("-uf",), True, False),
            (("-ru",), False, True),
            (("-urf",), True, True),
            (("-rfu",), True, True),
        ]
        for arguments, ignore_case, reverse in cases:
            with self.subTest(arguments=arguments):
                self.assert_unique_sorted(
                    input_data,
                    records,
                    *arguments,
                    ignore_case=ignore_case,
                    reverse=reverse,
                )

    def test_long_option_forms(self):
        records = [b"apple", b"APPLE", b"beta", b"BETA", b"z"]
        input_data = b"\n".join(records) + b"\n"
        self.assert_unique_sorted(
            input_data,
            records,
            "--reverse",
            "--ignore-case",
            "--unique",
            ignore_case=True,
            reverse=True,
        )

    def test_mixed_short_and_long_option_forms(self):
        records = [b"apple", b"APPLE", b"beta", b"BETA", b"z"]
        input_data = b"\n".join(records) + b"\n"
        forms = [
            ("-r", "--ignore-case", "--unique"),
            ("--reverse", "-f", "--unique"),
            ("--reverse", "--ignore-case", "-u"),
        ]
        self.assert_equivalent_forms(
            input_data, records, forms, ignore_case=True, reverse=True
        )

    def test_digits_punctuation_and_whitespace(self):
        records = [
            b"10",
            b"2",
            b"10",
            b"!mark",
            b"[mark",
            b" value",
            b"value ",
            b" value",
        ]
        self.assert_unique_sorted(b"\n".join(records) + b"\n", records)

    def test_embedded_nul_bytes(self):
        records = [b"a\x00b", b"a\x00b", b"a", b"a\x00", b"\x00"]
        self.assert_unique_sorted(b"\n".join(records) + b"\n", records)

    def test_multiple_embedded_nul_bytes(self):
        records = [b"x\x00\x00z", b"x\x00\x00z", b"x\x00\x00a", b"\x00\x00"]
        self.assert_unique_sorted(b"\n".join(records) + b"\n", records)

    def test_bytes_above_ascii(self):
        records = [b"\xff", b"\x80", b"\xff", b"\x7f", b"\x80"]
        self.assert_unique_sorted(b"\n".join(records) + b"\n", records)

    def test_mixed_ascii_and_non_ascii_bytes_with_ignore_case(self):
        records = [b"A\xff", b"a\xff", b"A\x80", b"a\x80", b"\x80A", b"\x80a"]
        self.assert_unique_sorted(
            b"\n".join(records) + b"\n", records, "-fu", ignore_case=True
        )

    def test_final_record_without_newline(self):
        records = [b"beta", b"alpha", b"beta"]
        self.assert_unique_sorted(b"beta\nalpha\nbeta", records)

    def test_one_byte_final_record_without_newline(self):
        self.assert_unique_sorted(b"x", [b"x"])

    def test_records_longer_than_four_kib_are_not_truncated(self):
        long_record = b"x" * 20000
        records = [long_record, b"short", long_record, b"x" * 5000]
        self.assert_unique_sorted(b"\n".join(records) + b"\n", records)

    def test_records_with_long_common_prefixes(self):
        prefix = b"p" * 10000
        records = [prefix + b"c", prefix + b"a", prefix, prefix + b"c"]
        self.assert_unique_sorted(b"\n".join(records) + b"\n", records)

    def test_large_number_of_duplicate_groups(self):
        records = []
        for index in range(1000, -1, -1):
            record = b"record-" + f"{index:04d}".encode("ascii")
            records.extend([record, record, record])
        self.assert_unique_sorted(b"\n".join(records) + b"\n", records)

    def test_large_number_of_records_in_one_group(self):
        records = [b"same"] * 5000
        self.assert_unique_sorted(b"\n".join(records) + b"\n", records)

    def test_selected_representatives_are_not_modified(self):
        records = [b"\x00Keep\xff ", b"\x00keep\xff ", b"Other", b"OTHER"]
        self.assert_unique_sorted(
            b"\n".join(records) + b"\n", records, "-fu", ignore_case=True
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

    def test_unique_with_value_fails(self):
        self.assert_invalid_arguments("--unique=value")

    def test_multiple_invalid_arguments_fail(self):
        self.assert_invalid_arguments("-u", "-x", "operand", "--unknown")

    def test_repeated_executions_do_not_share_process_state(self):
        cases = [
            ([b"z", b"a", b"z"], b"z\na\nz\n", ("-u",), False, False, True),
            ([b"z", b"a", b"z"], b"z\na\nz\n", (), False, False, False),
            ([], b"", ("--unique",), False, False, True),
            ([b"B", b"b", b"A"], b"B\nb\nA\n", ("-rfu",), True, True, True),
        ]
        for records, input_data, arguments, ignore_case, reverse, unique in cases:
            with self.subTest(records=records, arguments=arguments):
                self.assert_sorted(
                    input_data,
                    records,
                    *arguments,
                    unique=unique,
                    ignore_case=ignore_case,
                    reverse=reverse,
                )


if __name__ == "__main__":
    unittest.main()
