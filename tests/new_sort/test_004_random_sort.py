import subprocess
import unittest
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BINARY = ROOT / "build" / "new_sort"


def parse_output(output):
    if not output:
        return []
    return output[:-1].split(b"\n")


def ascii_fold(record):
    return bytes(value - 32 if 97 <= value <= 122 else value for value in record)


def exact_group_key(record):
    return record


def case_insensitive_group_key(record):
    return ascii_fold(record)


def group_key(record, ignore_case=False):
    if ignore_case:
        return case_insensitive_group_key(record)
    return exact_group_key(record)


def expected_groups(records, ignore_case=False):
    groups = {}
    for record in records:
        key = group_key(record, ignore_case)
        groups.setdefault(key, []).append(record)
    for members in groups.values():
        members.sort()
    return groups


def unique_representatives(records, ignore_case=False):
    return {
        key: members[0]
        for key, members in expected_groups(records, ignore_case).items()
    }


def serialize(records):
    return b"".join(record + b"\n" for record in records)


class NewSortRandomSortTests(unittest.TestCase):
    def run_sort(self, input_data, *arguments):
        return subprocess.run(
            [str(BINARY), *arguments],
            input=input_data,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def validate_random_output(
        self, result, input_records, ignore_case=False, unique=False
    ):
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, b"")

        groups = expected_groups(input_records, ignore_case)
        if groups:
            self.assertTrue(result.stdout.endswith(b"\n"))
        else:
            self.assertEqual(result.stdout, b"")
        output_records = parse_output(result.stdout)

        if unique:
            representatives = unique_representatives(input_records, ignore_case)
            self.assertEqual(Counter(output_records), Counter(representatives.values()))
        else:
            self.assertEqual(Counter(output_records), Counter(input_records))

        output_blocks = []
        seen_keys = set()
        for record in output_records:
            key = group_key(record, ignore_case)
            if not output_blocks or output_blocks[-1][0] != key:
                self.assertNotIn(key, seen_keys, "an equality group is not contiguous")
                seen_keys.add(key)
                output_blocks.append((key, [record]))
            else:
                output_blocks[-1][1].append(record)

        self.assertEqual(seen_keys, set(groups))
        self.assertEqual(len(output_blocks), len(groups))
        for key, members in output_blocks:
            if unique:
                self.assertEqual(members, [groups[key][0]])
            else:
                self.assertEqual(members, groups[key])

    def assert_random_properties(
        self,
        input_data,
        records,
        *arguments,
        ignore_case=False,
        unique=False,
        runs=3,
    ):
        if not arguments:
            arguments = ("-R",)
        for run in range(runs):
            with self.subTest(arguments=arguments, run=run):
                result = self.run_sort(input_data, *arguments)
                self.validate_random_output(
                    result,
                    records,
                    ignore_case=ignore_case,
                    unique=unique,
                )

    def assert_invalid_arguments(self, *arguments):
        result = self.run_sort(b"visible\nvisible\ninput\n", *arguments)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        self.assertIn(b"usage", result.stderr.lower())

    def test_short_random_sort_accepts_ordinary_input(self):
        records = [b"pear", b"apple", b"banana", b"apple"]
        self.assert_random_properties(b"\n".join(records) + b"\n", records, "-R")

    def test_long_random_sort_satisfies_same_properties(self):
        records = [b"z", b"alpha", b"middle", b"alpha", b"\xff"]
        self.assert_random_properties(
            b"\n".join(records) + b"\n", records, "--random-sort"
        )

    def test_uppercase_random_sort_is_distinct_from_lowercase_reverse(self):
        records = [b"delta", b"alpha", b"charlie", b"bravo"]
        input_data = b"\n".join(records) + b"\n"
        self.assert_random_properties(input_data, records, "-R")

        reverse_result = self.run_sort(input_data, "-r")
        self.assertEqual(reverse_result.returncode, 0)
        self.assertEqual(reverse_result.stdout, serialize(sorted(records, reverse=True)))
        self.assertEqual(reverse_result.stderr, b"")

    def test_empty_input(self):
        self.assert_random_properties(b"", [], "-R")

    def test_one_empty_record(self):
        self.assert_random_properties(b"\n", [b""], "-R")

    def test_one_nonempty_record(self):
        self.assert_random_properties(b"only\n", [b"only"], "-R")

    def test_all_records_equal(self):
        records = [b"same"] * 20
        self.assert_random_properties(b"\n".join(records) + b"\n", records)

    def test_all_records_distinct(self):
        records = [b"delta", b"alpha", b"charlie", b"bravo"]
        self.assert_random_properties(b"\n".join(records) + b"\n", records)

    def test_duplicate_groups_with_different_counts(self):
        records = [b"beta", b"alpha", b"gamma", b"beta", b"alpha", b"beta"]
        self.assert_random_properties(b"\n".join(records) + b"\n", records)

    def test_multiple_empty_records(self):
        records = [b"", b"", b""]
        self.assert_random_properties(b"\n\n\n", records)

    def test_empty_records_mixed_with_nonempty_records(self):
        records = [b"", b"word", b"", b"word", b"z"]
        self.assert_random_properties(b"\nword\n\nword\nz\n", records)

    def test_prefix_related_records(self):
        records = [b"a", b"aa", b"aaa", b"a", b"ab"]
        self.assert_random_properties(b"\n".join(records) + b"\n", records)

    def test_leading_and_trailing_spaces(self):
        records = [b"value", b" value", b"value ", b" value ", b"value"]
        self.assert_random_properties(b"\n".join(records) + b"\n", records)

    def test_tabs_and_non_newline_control_bytes(self):
        records = [b"a b", b"a\tb", b"a\rb", b"a\x01b", b"a b"]
        self.assert_random_properties(b"\n".join(records) + b"\n", records)

    def test_punctuation_and_digits(self):
        records = [b"10", b"2", b"10", b"!mark", b"[mark", b"~", b"0"]
        self.assert_random_properties(b"\n".join(records) + b"\n", records)

    def test_embedded_nul_bytes(self):
        records = [b"a\x00b", b"a\x00b", b"a", b"a\x00", b"\x00"]
        self.assert_random_properties(b"\n".join(records) + b"\n", records)

    def test_multiple_embedded_nul_bytes(self):
        records = [b"x\x00\x00z", b"x\x00\x00z", b"x\x00\x00a", b"\x00\x00"]
        self.assert_random_properties(b"\n".join(records) + b"\n", records)

    def test_bytes_above_ascii(self):
        records = [b"\xff", b"\x80", b"\xff", b"\x7f", b"\x80"]
        self.assert_random_properties(b"\n".join(records) + b"\n", records)

    def test_mixed_ascii_and_non_ascii_bytes(self):
        records = [b"A\xff", b"a\xff", b"A\x80", b"\x80A", b"\x80a"]
        self.assert_random_properties(b"\n".join(records) + b"\n", records)

    def test_final_record_without_newline(self):
        records = [b"beta", b"alpha", b"beta"]
        self.assert_random_properties(b"beta\nalpha\nbeta", records)

    def test_one_byte_final_record_without_newline(self):
        self.assert_random_properties(b"x", [b"x"])

    def test_records_longer_than_four_kib_are_not_truncated(self):
        long_record = b"x" * 20000
        records = [long_record, b"short", long_record, b"x" * 5000]
        self.assert_random_properties(
            b"\n".join(records) + b"\n", records, runs=2
        )

    def test_records_with_long_common_prefixes(self):
        prefix = b"p" * 10000
        records = [prefix + b"c", prefix + b"a", prefix, prefix + b"c"]
        self.assert_random_properties(
            b"\n".join(records) + b"\n", records, runs=2
        )

    def test_large_number_of_distinct_groups(self):
        records = [b"record-" + f"{index:04d}".encode("ascii") for index in range(1000)]
        self.assert_random_properties(
            b"\n".join(records) + b"\n", records, runs=2
        )

    def test_large_number_of_duplicate_records(self):
        records = [b"same"] * 5000
        self.assert_random_properties(
            b"\n".join(records) + b"\n", records, runs=2
        )

    def test_ignore_case_groups_are_contiguous_and_in_deterministic_order(self):
        records = [b"apple", b"APPLE", b"Apple", b"beta", b"BETA", b"z"]
        self.assert_random_properties(
            b"\n".join(records) + b"\n",
            records,
            "-Rf",
            ignore_case=True,
        )

    def test_unique_outputs_one_representative_per_exact_group(self):
        records = [b"beta", b"alpha", b"beta", b"gamma", b"alpha"]
        self.assert_random_properties(
            b"\n".join(records) + b"\n", records, "-Ru", unique=True
        )

    def test_ignore_case_unique_uses_deterministic_representatives(self):
        records = [b"apple", b"APPLE", b"Apple", b"beta", b"BETA", b"z"]
        self.assert_random_properties(
            b"\n".join(records) + b"\n",
            records,
            "-Rfu",
            ignore_case=True,
            unique=True,
        )

    def test_reverse_preserves_groups_and_internal_member_order(self):
        records = [b"beta", b"alpha", b"beta", b"gamma", b"alpha"]
        self.assert_random_properties(
            b"\n".join(records) + b"\n", records, "-Rr"
        )

    def test_reverse_ignore_case_unique_does_not_change_representatives(self):
        records = [b"apple", b"APPLE", b"Apple", b"beta", b"BETA", b"z"]
        self.assert_random_properties(
            b"\n".join(records) + b"\n",
            records,
            "-Rrfu",
            ignore_case=True,
            unique=True,
        )

    def test_supported_combined_short_forms(self):
        records = [b"apple", b"APPLE", b"beta", b"beta", b"z"]
        input_data = b"\n".join(records) + b"\n"
        cases = [
            (("-Rf",), True, False),
            (("-fR",), True, False),
            (("-Ru",), False, True),
            (("-Rfu",), True, True),
            (("-Rrfu",), True, True),
        ]
        for arguments, ignore_case, unique in cases:
            with self.subTest(arguments=arguments):
                self.assert_random_properties(
                    input_data,
                    records,
                    *arguments,
                    ignore_case=ignore_case,
                    unique=unique,
                    runs=2,
                )

    def test_separate_short_forms(self):
        records = [b"apple", b"APPLE", b"beta", b"BETA", b"z"]
        self.assert_random_properties(
            b"\n".join(records) + b"\n",
            records,
            "-R",
            "-r",
            "-f",
            "-u",
            ignore_case=True,
            unique=True,
        )

    def test_long_option_forms(self):
        records = [b"apple", b"APPLE", b"beta", b"BETA", b"z"]
        self.assert_random_properties(
            b"\n".join(records) + b"\n",
            records,
            "--random-sort",
            "--reverse",
            "--ignore-case",
            "--unique",
            ignore_case=True,
            unique=True,
        )

    def test_mixed_short_and_long_option_forms(self):
        records = [b"apple", b"APPLE", b"beta", b"BETA", b"z"]
        self.assert_random_properties(
            b"\n".join(records) + b"\n",
            records,
            "-Rr",
            "--ignore-case",
            "--unique",
            ignore_case=True,
            unique=True,
        )

    def test_option_order_does_not_change_grouping_or_representative_rules(self):
        records = [b"apple", b"APPLE", b"beta", b"BETA", b"z"]
        input_data = b"\n".join(records) + b"\n"
        forms = [
            ("-R", "-r", "-f", "-u"),
            ("-u", "-f", "-r", "-R"),
            ("-f", "-R", "-u", "-r"),
            ("-r", "-u", "-R", "-f"),
        ]
        for arguments in forms:
            with self.subTest(arguments=arguments):
                self.assert_random_properties(
                    input_data,
                    records,
                    *arguments,
                    ignore_case=True,
                    unique=True,
                    runs=2,
                )

    def test_repeated_clustered_random_sort_is_accepted(self):
        records = [b"c", b"a", b"c", b"b"]
        self.assert_random_properties(b"c\na\nc\nb\n", records, "-RR")

    def test_repeated_long_random_sort_is_accepted(self):
        records = [b"c", b"a", b"c", b"b"]
        self.assert_random_properties(
            b"c\na\nc\nb\n", records, "--random-sort", "--random-sort"
        )

    def test_sort_random_long_option_is_rejected(self):
        self.assert_invalid_arguments("--sort=random")

    def test_random_source_without_value_is_rejected(self):
        self.assert_invalid_arguments("--random-source")

    def test_random_source_with_value_is_rejected(self):
        self.assert_invalid_arguments("--random-source=value")

    def test_random_sort_with_value_is_rejected(self):
        self.assert_invalid_arguments("--random-sort=value")

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

    def test_multiple_invalid_arguments_fail(self):
        self.assert_invalid_arguments("-R", "-x", "operand", "--unknown")

    def test_repeated_executions_always_satisfy_required_properties(self):
        records = [b"apple", b"APPLE", b"beta", b"BETA", b"z", b"z"]
        self.assert_random_properties(
            b"\n".join(records) + b"\n",
            records,
            "-Rrf",
            ignore_case=True,
            runs=8,
        )


if __name__ == "__main__":
    unittest.main()
