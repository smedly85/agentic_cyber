# Rust historical depth accounting — measurement blocked

No historical build or semantic measurement was attempted. `—` is missing, not zero.
The required controlled trait-object dispatch case failed. No distributions exist.

| CVE | Utility/component | Vulnerable function(s) | Function depth(s) | CVE min depth | Status |
| --- | --- | --- | --- | --- | --- |
| CVE-2021-29934 | od | PartialReader<R>::read | — | — | analysis_failure; controlled-instrument gate |
| CVE-2026-35338 | chmod | Chmoder::chmod | — | — | analysis_failure; controlled-instrument gate |
| CVE-2026-35339 | chmod | Chmoder::chmod | — | — | analysis_failure; controlled-instrument gate |
| CVE-2026-35340 | uucore/perms | ChownExecutor::dive_into | — | — | analysis_failure; controlled-instrument gate |
| CVE-2026-35341 | mkfifo | uumain | — | — | analysis_failure; controlled-instrument gate |
| CVE-2026-35342 | mktemp | Options::from | — | — | analysis_failure; controlled-instrument gate |
| CVE-2026-35343 | cut | cut_fields_newline_char_delim | — | — | analysis_failure; controlled-instrument gate |
| CVE-2026-35344 | dd | BlockWriter::truncate | — | — | analysis_failure; controlled-instrument gate |
| CVE-2026-35345 | tail | Observer::handle_event | — | — | analysis_failure; controlled-instrument gate |
| CVE-2026-35346 | comm | comm | — | — | analysis_failure; controlled-instrument gate |
| CVE-2026-35347 | comm | are_files_identical | — | — | analysis_failure; controlled-instrument gate |
| CVE-2026-35348 | sort | uumain | — | — | analysis_failure; controlled-instrument gate |
| CVE-2026-35349 | rm | handle_dir | — | — | analysis_failure; controlled-instrument gate |
| CVE-2026-35350 | cp | copy_attributes | — | — | analysis_failure; controlled-instrument gate |
| CVE-2026-35351 | mv | rename_file_fallback; copy_file_with_hardlinks_helper; copy_dir_contents_recursive | — | — | analysis_failure; controlled-instrument gate |
| CVE-2026-35352 | mkfifo | uumain | — | — | analysis_failure; controlled-instrument gate |
| CVE-2026-35353 | mkdir | create_dir | — | — | analysis_failure; controlled-instrument gate |
| CVE-2026-35354 | uucore/fsxattr | copy_xattrs; retrieve_xattrs; apply_xattrs | — | — | analysis_failure; controlled-instrument gate |
| CVE-2026-35355 | install | copy_file | — | — | analysis_failure; controlled-instrument gate |
| CVE-2026-35356 | install | standard; copy_file | — | — | analysis_failure; controlled-instrument gate |
| CVE-2026-35357 | cp | clone; sparse_copy_without_hole; sparse_copy | — | — | mapping_unresolved_partial; measurement blocked |
| CVE-2026-35358 | cp | copy_helper | — | — | analysis_failure; controlled-instrument gate |
| CVE-2026-35359 | cp | clone; sparse_copy_without_hole; sparse_copy; copy_stream; copy_on_write; copy_on_write; copy_on_write | — | — | mapping_unresolved_partial; measurement blocked |
| CVE-2026-35360 | touch | touch_file | — | — | analysis_failure; controlled-instrument gate |
| CVE-2026-35361 | mknod | mknod | — | — | analysis_failure; controlled-instrument gate |
| CVE-2026-35362 | configuration/platform selection | not applicable | — | — | not_applicable |
| CVE-2026-35363 | rm | path_is_current_or_parent_directory | — | — | analysis_failure; controlled-instrument gate |
| CVE-2026-35364 | mv | rename_file_fallback | — | — | analysis_failure; controlled-instrument gate |
| CVE-2026-35365 | mv | copy_dir_contents_recursive | — | — | analysis_failure; controlled-instrument gate |
| CVE-2026-35366 | printenv | uumain | — | — | analysis_failure; controlled-instrument gate |
| CVE-2026-35367 | nohup | find_stdout | — | — | analysis_failure; controlled-instrument gate |
| CVE-2026-35368 | chroot | set_context | — | — | analysis_failure; controlled-instrument gate |
| CVE-2026-35369 | kill | uu_app | — | — | analysis_failure; controlled-instrument gate |
| CVE-2026-35370 | id | uumain | — | — | analysis_failure; controlled-instrument gate |
| CVE-2026-35371 | id | pretty | — | — | analysis_failure; controlled-instrument gate |
| CVE-2026-35372 | ln | link_files_in_dir | — | — | analysis_failure; controlled-instrument gate |
| CVE-2026-35373 | ln | link_files_in_dir | — | — | analysis_failure; controlled-instrument gate |
| CVE-2026-35374 | split | instantiate_current_writer; instantiate_current_writer | — | — | analysis_failure; controlled-instrument gate |
| CVE-2026-35375 | split | FilenameIterator::next | — | — | analysis_failure; controlled-instrument gate |
| CVE-2026-35376 | chcon | process_file; change_file_context | — | — | analysis_failure; controlled-instrument gate |
| CVE-2026-35377 | env | SplitIterator::split_single_quoted_backslash | — | — | analysis_failure; controlled-instrument gate |
| CVE-2026-35378 | expr | Parser::parse_simple_expression | — | — | analysis_failure; controlled-instrument gate |
| CVE-2026-35379 | tr | Sequence::flatten | — | — | analysis_failure; controlled-instrument gate |
| CVE-2026-35380 | cut | get_delimiters | — | — | analysis_failure; controlled-instrument gate |
| CVE-2026-35381 | cut | cut_fields_newline_char_delim | — | — | analysis_failure; controlled-instrument gate |
