"""Human source/patch review decisions, not inferred from changed-function lists.

Input to freeze.py. No graph, compilation, reachability or measurement code.
Function names refer to the vulnerable release, not to newly introduced fixes.
"""

# number: component, functions in the component's principal source file,
#         primary fix (merged PR number or exact commit), mapping rationale
REVIEWS = {
    29934: ("od", ["PartialReader<R>::read"], "39d62c6c1f809022c903180471c10fde6ecd12d1",
            "The Read implementation exposes uninitialized Vec storage to a safe Read implementation after set_len; RustSec identifies PartialReader and the patch replaces this allocation."),
    35338: ("chmod", ["Chmoder::chmod"], 10033,
            "The preserve-root guard compares the pathname literally with slash, permitting alternate paths to the root. This is the defective guard, not the replacement root-identification helper."),
    35339: ("chmod", ["Chmoder::chmod"], 9793,
            "The recursive loop replaces its accumulated result with each child's result, so a later success masks an earlier failure."),
    35340: ("uucore/perms", ["ChownExecutor::dive_into"], 10035,
            "The shared ownership traversal overwrites the accumulated status while visiting children; the patch combines results instead. Both chown and chgrp use this executor."),
    35341: ("mkfifo", ["uumain"], 10376,
            "After FIFO creation fails, control continues to chmod the existing path. The fix adds the missing continue; command-building and regression tests are not vulnerable locations."),
    35342: ("mktemp", ["Options::from"], 10566,
            "An empty TMPDIR is accepted as the temporary directory rather than selecting the secure fallback, allowing creation relative to the current directory."),
    35343: ("cut", ["cut_fields_newline_char_delim"], 11143,
            "The special field-splitting path for a delimiter equal to the record separator omits only-delimited filtering. The enclosing cut_fields change only propagates the option."),
    35344: ("dd", ["BlockWriter::truncate"], "0f538b942a5cdaba6e0960f6952429a1baaedf93",
            "This wrapper discards truncate errors with .ok() for both buffered and unbuffered outputs. Dest::truncate already returns errors; finalize is changed to propagate the newly returned result."),
    35345: ("tail", ["Observer::handle_event"], "2c2f1b0c1f11f120fc8cbf8d518194f6532c0607",
            "Replacement events use following metadata to decide whether the replacement is tailable, accepting a symlink target under follow-by-name. The fix explicitly checks symlink_metadata here."),
    35346: ("comm", ["comm"], 10206,
            "All three output-column branches convert arbitrary input bytes through String::from_utf8_lossy before printing, corrupting non-UTF-8 data. The added byte-writing helper is a fix, not a vulnerable function."),
    35347: ("comm", ["are_files_identical"], 9545,
            "The identity/content precheck consumes non-regular inputs such as FIFOs before the comparison, causing hangs or lost input. The fix restricts the precheck to regular files."),
    35348: ("sort", ["uumain"], 12773,
            "The files0-from filename decoding uses from_utf8(...).expect on arbitrary filename bytes, causing a panic rather than accepting non-UTF-8 paths."),
    35349: ("rm", ["handle_dir"], 9706,
            "The preserve-root predicate only recognizes lexical root paths, allowing aliases to reach recursive removal. The fix replaces the predicate and adds a precheck in remove; the latter propagates the same root policy."),
    35350: ("cp", ["copy_attributes"], "bd170a5d4b19ed985417d322dffb8cade2cbbad5",
            "A failed ownership change is ignored before restoring source permissions including setuid/setgid, potentially retaining special bits under the wrong owner."),
    35351: ("mv", ["rename_file_fallback", "copy_file_with_hardlinks_helper", "copy_dir_contents_recursive"], 11706,
            "Upstream issue 9714 explicitly identifies these three ownership-losing cross-device copy paths. The vulnerable source performs copy/creation without restoring source ownership. Later remediation of other sites is not sufficient to add vulnerable locations."),
    35352: ("mkfifo", ["uumain"], "c004672c5eb2415b03f11f766583c4b967ba024f",
            "FIFO creation followed by pathname-based set_permissions allows a replacement symlink to redirect the permission change; both operations are in uumain."),
    35353: ("mkdir", ["create_dir"], 10036,
            "Directory creation followed by pathname-based chmod allows replacement between operations. At the audited release the function is create_dir; the later patch's create_single_dir name must not replace this vulnerable identity."),
    35354: ("uucore/fsxattr", ["copy_xattrs", "retrieve_xattrs", "apply_xattrs"], 10545,
            "The shared xattr routines perform repeated pathname-based list/get/set operations, allowing different inode resolutions within preservation. mv's cross-device callers and the FD-based replacements establish the mapping."),
    35355: ("install", ["copy_file"], 10067,
            "The destination is removed and recreated by pathname without exclusive creation, permitting a symlink substitution before the copy."),
    35356: ("install", ["standard", "copy_file"], 10140,
            "standard creates destination parents without retaining an anchored directory descriptor; copy_file later opens the path independently. These are the two vulnerable path-resolution stages, not merely diagnostic changes."),
    35357: ("cp", [], "681030bca3d5fc8fa4886b75eaefc2ca04471668",
            "In the pinned source this function uses File::create for the destination without a restrictive creation mode. Under umask 022 the new file can be readable as 0644 before copy_file later applies a private source's 0600 mode; an already-open attacker descriptor survives that tightening. This directly matches issue 10011, independently of later patch membership."),
    35358: ("cp", ["copy_helper"], 11163,
            "Recursive copy dispatch handles FIFOs and sockets specially but lets character/block devices enter the content-copy path. copy_file and handle_copy_mode changes propagate metadata; the defective type dispatch is here."),
    35359: ("cp", [], "ef5d75228262d62f3ff2ad21d35323b1f6665820",
            "The pinned copy_file no-dereference branch obtains symlink_metadata; handle_copy_mode and copy_helper use that saved classification to select content copying. The same source pathname is then reopened here without binding it to the checked inode. Location-specific reasons below establish actual content transfer, not merely an open or a later patch edit."),
    35360: ("touch", ["touch_file"], "ca0c842e71a9f75b31c87f701952f9e174a320ce",
            "A missing-path check followed by File::create permits an attacker to substitute a symlink and cause truncation of its target."),
    35361: ("mknod", ["mknod"], 10582,
            "The vulnerable fn mknod(file_name: &str, config: Config) -> i32 attempts std::fs::remove_dir on a device/FIFO after SELinux context application fails. PR 10582 directly replaces it with std::fs::remove_file inside this function. The function mapping is verified irrespective of broader atomic-labeling remediation history."),
    35362: ("uucore/safe_traversal", [], 9792,
            "Linux-only cfg gates disable descriptor-relative traversal protections on other Unix targets. The defect is platform configuration across modules/call sites, not one function's implementation."),
    35363: ("rm", ["path_is_current_or_parent_directory"], "d0e5af23217ed671eeb8db586f12d6dc6cd79b75",
            "The lexical dot/dot-dot safety predicate fails to account for trailing path separators; normalization is added before the safety decision."),
    35364: ("mv", ["rename_file_fallback"], "7183073b3259ba06241b29470a9e7accbb4096e7",
            "The regular-file cross-device fallback unlinks an existing destination before copying by pathname, allowing a symlink to be inserted in that interval. The fix keeps existing regular destinations in place."),
    35365: ("mv", ["copy_dir_contents_recursive"], 10546,
            "The recursive cross-device copy classifies entries with following is_dir and copies other paths as files, expanding symlink targets instead of preserving links. The patch adds no-follow symlink classification at this site."),
    35366: ("printenv", ["uumain"], 9728,
            "env::vars and env::var assume Unicode environment data, causing panic or rejection for non-UTF-8 variables; the fix uses OS-string environment APIs."),
    35367: ("nohup", ["find_stdout"], 12339,
            "Both current-directory and HOME output-file creation paths omit an explicit restrictive creation mode, allowing umask-derived disclosure of nohup output."),
    35368: ("chroot", ["set_context"], 11211,
            "The routine enters the new root before resolving user/group names, allowing the new root's identity databases to influence privilege selection."),
    35369: ("kill", ["uu_app"], 9700,
            "The command parser's allow_negative_numbers setting changes signal-option interpretation. This runtime command-building function contains the defective parser policy; it is not a build-system issue."),
    35370: ("id", ["uumain"], "ff382f527994b8a021ec0a086dec4c5cafa34f2a",
            "Default and groups-only forms derive their group lists from the same gid despite differing real/effective-gid ordering requirements. The fix separates selection in uumain."),
    35371: ("id", ["pretty"], "18a50ff513444da99dd8e09451ebecd2ebbe5758",
            "The pretty formatter obtains getegid where geteuid is required and compares/labels identities incorrectly, giving incorrect effective-user output."),
    35372: ("ln", ["link_files_in_dir"], 11253,
            "The destination-directory symlink no-dereference policy is incorrectly conditional on force, so no-dereference alone can redirect link creation."),
    35373: ("ln", ["link_files_in_dir"], 11403,
            "Source basenames are converted with to_str, rejecting non-UTF-8 filenames before destination path construction."),
    35374: ("split", [], "58040feb5c66fce588a7ffac299b3a23bd55cd81",
            "A pathname identity check precedes an output open that truncates before validating the opened inode. The platform writer constructors perform that destructive open; the check/open pair is the reported race."),
    35375: ("split", ["FilenameIterator::next"], 11397,
            "Lossy Unicode conversion of output prefix/suffix aliases distinct byte filenames, allowing unintended output collisions and overwrites."),
    35376: ("chcon", ["process_file", "change_file_context"], "7cfc74e47ffab452663be6842d788a5164d9688b",
            "process_file resolves an fts_accpath afresh rather than relative to traversal state; change_file_context performs pathname SELinux get/set operations. The fix binds resolution and relabeling to descriptors."),
    35377: ("env", ["SplitIterator::split_single_quoted_backslash"], "9d7a0e849109c82262ac2d65324739aac690200f",
            "The single-quote parser interprets or rejects backslash escapes instead of preserving them literally, changing env -S argument splitting."),
    35378: ("expr", ["Parser::parse_simple_expression"], 11395,
            "Parenthesized expressions are evaluated while parsing, before boolean short-circuit evaluation can suppress them. Removing the eager evaluated call fixes the vulnerable parse site."),
    35379: ("tr", ["Sequence::flatten"], 11405,
            "The character-class expansion treats the graph/print boundary incorrectly for space, changing translation/filter behavior."),
    35380: ("cut", ["get_delimiters"], 11399,
            "Both input and output delimiter parsing treat two literal apostrophes as an empty delimiter, confusing shell quoting with actual argument bytes."),
    35381: ("cut", ["cut_fields_newline_char_delim"], 11143,
            "With NUL record separators and matching delimiters, the optimized field path fails to suppress undelimited records. The same vulnerable function also appears under 35343; distinct CVE IDs are retained."),
}

FILES = {
    29934: "src/uu/od/src/partialreader.rs",
    35340: "src/uucore/src/lib/features/perms.rs",
    35345: "src/uu/tail/src/follow/watch.rs",
    35354: "src/uucore/src/lib/features/fsxattr.rs",
    35375: "src/uu/split/src/filenames.rs",
    35377: "src/uu/env/src/split_iterator.rs",
    35378: "src/uu/expr/src/syntax_tree.rs",
    35379: "src/uu/tr/src/operation.rs",
}

PLATFORM_FUNCTIONS = {
    35357: {"src/uu/cp/src/platform/linux.rs": ["clone", "sparse_copy_without_hole", "sparse_copy"]},
    35359: {"src/uu/cp/src/platform/linux.rs": ["clone", "sparse_copy_without_hole", "sparse_copy", "copy_stream", "copy_on_write"],
            "src/uu/cp/src/platform/other_unix.rs": ["copy_on_write"],
            "src/uu/cp/src/platform/macos.rs": ["copy_on_write"]},
    35374: {"src/uu/split/src/platform/unix.rs": ["instantiate_current_writer"],
            "src/uu/split/src/platform/windows.rs": ["instantiate_current_writer"]},
}

# An unresolved record can contain verified lower-bound locations. It is never
# presented as an exhaustive mapping or silently excluded from the population.
UNRESOLVED = {
    35357: "Three Linux File::create sites directly establish the disclosed transient-readable-permissions defect. The patch also hardens stream write permissions and std::fs::copy fallbacks on multiple platforms. Those changes alone do not prove all such sites independently expose private contents: historical standard-library creation semantics and the CVE scope of the write-permission variant need review. They are not promoted to vulnerable functions merely because the patch touched them.",
    35359: "Seven source-qualified content-copy locations are confirmed from the common no-dereference check/use sequence, including explicit stream opens on other Unix and macOS. The previous other.rs mapping is withdrawn: that is the non-Unix backend, not other_unix.rs, and the Linux O_NOFOLLOW evidence does not establish its native copy semantics. Exhaustive coverage still requires primary evidence for the non-Unix delegated copy and macOS clonefile/native fallback semantics. Probe-only opens are not automatically vulnerable locations.",
}

CAVEATS = {
    35344: "Output::new_file also suppresses a set_len error in this release, but the advisory and substantive fix identify final BlockWriter truncation. Do not infer an additional CVE location from a superficially similar operation without primary scope evidence.",
    35345: "The earlier PR 10397 was closed without merging. Use the substantive follow-by-name fix in commit 2c2f1b0, not that proposal's SHA.",
    35349: "is_root_path and show_preserve_root_error are newly introduced helpers, not vulnerable functions. remove receives an early safety check; the existing incorrect root decision is in handle_dir.",
    35351: "The verified mapping is restricted to the three paths explicitly named by upstream issue 9714. PR 11706 additionally changes rename_symlink_fallback and copy_dir_contents for remediation completeness; those changes alone do not establish them as CVE locations. Neither those functions nor rename_fifo_fallback is included without stronger primary vulnerability evidence.",
    35353: "The vulnerable create_dir identity differs from the later patch's create_single_dir after intervening refactoring.",
    35354: "The CVE is assigned to uu_mv, but the defective implementation is shared uucore code. mv is explicitly affected. cp also calls copy_xattrs in the selected source and the corrective patch hardens cp; record it as source-supported expected exposure, not a separate CVE assignment. The later PR 10545 completes directory xattr binding; commit 54877ac475fa24b8f4b73cb4e6e286f9e7ab45f0 is the earlier file-path remediation.",
    35357: "The advisory calls issue 10011 a PR; that URL is an issue, not a merged patch. The exact restrictive-creation commit is recorded instead. The patch explicitly discusses stream write-permission hardening, which is not automatically evidence of the private-read disclosure described by this CVE.",
    35361: "Mapping to mknod is verified. PR 10582 proves the remove_dir-to-remove_file cleanup correction directly inside that function. Whether a separate change makes SELinux labeling atomic is solely a remediation-history nuance, not uncertainty about the vulnerable-function mapping.",
    35362: "The configuration defect is retained, not dropped because no singular runtime function can be assigned. The reviewed corrective patch establishes affected consumer gates in chmod, du and rm; do not infer all other uucore consumers are affected.",
    35364: "The recorded commit removes early unlinking for regular destinations. It is not a claim to fix every possible destination race. The separately disclosed cross-device directory recreation issue is not silently merged into this CVE.",
    35370: "The repository advisory's structured patched version is 0.11.0 while narrative text describes older releases as unfixed. The substantive August 2026 group-ordering commit resolves the discrepancy; the closed PR 10706 is not the fix.",
    35374: "The Settings-level identity check is part of the race context; it does not itself open/truncate a victim. Platform output constructors are the independently destructive locations. No reachability calculation was used to choose platforms.",
    35376: "Both the traversal-relative resolution and pathname SELinux operation are retained, rather than selecting only one of the changed functions. Added dirfd accessors are repair infrastructure.",
    35381: "The CNA links PR 11394, whose production-code delta is whitespace after the earlier substantive PR 11143. Record the earlier runtime correction as the fix and preserve the later reference as corroborating regression evidence, not a second vulnerable identity.",
}

EXECUTABLES = {35340: ["chgrp", "chown"], 35354: ["mv", "cp"],
               35362: ["chmod", "du", "rm"]}

CONFIGURATION_FILES = ["src/uucore/src/lib/features.rs", "src/uucore/src/lib/lib.rs",
                       "src/uu/chmod/src/chmod.rs", "src/uu/du/src/du.rs",
                       "src/uu/rm/src/platform/mod.rs", "src/uu/rm/src/rm.rs"]

# Narrow pre-measurement re-audit. These are source-level check/use reviews,
# not semantic call-graph construction or measurements.
AUDIT_SOURCE_FILES = {
    number: ["src/uu/cp/src/cp.rs", "src/uu/cp/src/platform/mod.rs",
             "src/uu/cp/src/platform/linux.rs", "src/uu/cp/src/platform/other_unix.rs",
             "src/uu/cp/src/platform/macos.rs", "src/uu/cp/src/platform/other.rs"]
    for number in (35357, 35359)
}

LOCATION_REASONS = {
    (35359, "src/uu/cp/src/platform/linux.rs", "clone"):
        "After the saved no-dereference classification selects content copying, linux.rs:61 opens that source pathname with File::open, then FICLONE copies from its descriptor; line 79 can also reopen it via std::fs::copy on fallback. Neither use is bound to the earlier checked inode.",
    (35359, "src/uu/cp/src/platform/linux.rs", "sparse_copy_without_hole"):
        "After the common no-dereference classification selects sparse content copying, linux.rs:135 reopens the same pathname with File::open; read_exact_at/write_all_at transfer from that descriptor to the destination. No O_NOFOLLOW or inode binding protects the check/use interval.",
    (35359, "src/uu/cp/src/platform/linux.rs", "sparse_copy"):
        "After the common no-dereference classification selects sparse copying, linux.rs:185 reopens the same pathname with File::open and reads bytes from that descriptor for destination writes, without O_NOFOLLOW or binding to the checked inode.",
    (35359, "src/uu/cp/src/platform/linux.rs", "copy_stream"):
        "For a source classified as a FIFO/device (cp.rs:2432,2502-2506), non-recursive content copying or recursive --copy-contents passes the non-symlink decision into this stream branch. linux.rs:247 reopens the pathname without O_NOFOLLOW and buf_copy transfers its contents. Replacing the checked FIFO/device with a symlink before that open copies the target; this is not the regular-file branch.",
    (35359, "src/uu/cp/src/platform/linux.rs", "copy_on_write"):
        "This is included for its own std::fs::copy(source,dest) sites at linux.rs:298,314,333, not for dispatch to other mapped functions. A regular source classified under no-dereference can take ReflinkMode::Never and SparseMode::Never to line 314; no checked descriptor is passed and the copying operation reopens the pathname. Issue 10017's Linux open evidence and the substantive fix support this use site.",
    (35359, "src/uu/cp/src/platform/other_unix.rs", "copy_on_write"):
        "Confirmed specifically for the explicit stream branch: ReflinkMode::Never/SparseMode::Auto accepts the saved non-symlink FIFO/device classification, then other_unix.rs:45 calls File::open on the original pathname and buf_copy transfers from that descriptor. There is no O_NOFOLLOW or inode binding. The delegated fs::copy at line 66 is separately recorded for completeness, not used to invent a native open implementation.",
    (35359, "src/uu/cp/src/platform/macos.rs", "copy_on_write"):
        "Confirmed specifically for the explicit stream fallback at macos.rs:95 when clonefile is unavailable/fails and reflink is not Always. It consumes the saved no-dereference FIFO/device classification, reopens the original pathname with File::open without O_NOFOLLOW, and copies from that descriptor. This source-supported association does not assert that every clonefile branch has identical symlink semantics.",
}

AUDIT_NOTES = {
    35351: """## Narrow pre-measurement audit

Primary [issue 9714](https://github.com/uutils/coreutils/issues/9714) expressly
identifies rename_file_fallback, copy_file_with_hardlinks_helper and
copy_dir_contents_recursive. Their source in the pinned release contains the
reported ownership-losing copy/creation operations. These three, and only these
three, are the verified vulnerable-function population for this CVE.

[PR 11706](https://github.com/uutils/coreutils/pull/11706) also restores ownership
in rename_symlink_fallback and copy_dir_contents. No stronger primary vulnerability
evidence was found establishing those two as independently vulnerable CVE locations;
they are recorded as remediation-completeness changes, not included mappings.
The added preserve_ownership helper and tests are not vulnerable-release functions.
The previous speculation about standalone rename_fifo_fallback does not establish
an additional location either. Mapping status is verified against the explicit
issue scope, not against all locations touched by the later patch.
""",
    35357: """## Narrow pre-measurement audit

Primary [issue 10011](https://github.com/uutils/coreutils/issues/10011) establishes
the private-read disclosure mechanism. All line numbers below refer to exact
revision 3a07ffc5a9bd4c283e75afa548ba1f1957bad242, not the fixed source.

Confirmed destination-creation sites in src/uu/cp/src/platform/linux.rs:

- clone, line 62: File::create precedes FICLONE or the fallback copy.
- sparse_copy_without_hole, line 136: File::create precedes sizing and data writes.
- sparse_copy, line 186: File::create precedes sizing and sparse data writes.

These calls specify no restrictive creation mode. For a previously absent
destination, mode 0666 masked by umask 022 permits reads as 0644 even when the
source is 0600. In cp.rs, calculate_dest_permissions (2230-2258) computes the
eventual mode, but copy_file invokes content copying (2434-2446) before
set_permissions (2460). That later tightening closes the pathname permission
window but cannot revoke a descriptor obtained during creation/copying.
clone is not exempt merely because it may use an ioctl rather than a byte loop.

Other creation/open paths were reviewed but are not silently added:

- linux.rs copy_stream (249-253), other_unix.rs copy_on_write (47-51) and macos.rs
  copy_on_write (97-101) explicitly use 0622 masked by umask. Group/other write
  exposure is not proof of this CVE's private-read disclosure.
- std::fs::copy calls in linux.rs clone (79), linux.rs copy_on_write (298,314,333),
  other_unix.rs (66), macos.rs (113) and non-Unix other.rs (37) delegate creation
  semantics to the standard library. The later patch's replacement of those
  calls does not establish their historical creation mode by itself.
- macOS clonefile calls use an OS primitive rather than File::create; source
  alone does not establish an initially overbroad mode for that primitive.
- cp.rs handle_copy_mode's AttrOnly open (2206-2210) creates an attribute-only
  destination, not a copy of private contents. FIFO/socket/directory creation
  is not the demonstrated regular-file-content exposure. Backup copying uses
  the old destination as input, not the checked source of this finding.
- calculate_dest_permissions, copy_file and copy_attributes supply mode policy
  or eventual tightening; they do not themselves perform these three unsafe
  destination creations and are not counted again as independent locations.

The three existing confirmed locations remain justified. A complete cross-platform
set is not proven without historical standard-library/OS creation evidence;
mapping_status remains unresolved. No later remediation helper is included merely
because a patch changes it.
""",
    35359: """## Narrow pre-measurement audit

Primary [issue 10017](https://github.com/uutils/coreutils/issues/10017) establishes
the metadata-check/path-open race. This is a manual source check/use audit, not
construction of a semantic call graph. All line numbers refer to exact revision
3a07ffc5a9bd4c283e75afa548ba1f1957bad242.

The common decision is in cp.rs:2406-2418: when dereference is false it obtains
symlink_metadata. handle_copy_mode derives source_is_symlink from that saved
metadata (2087-2089). copy_helper (2583-2600) selects a link-preserving operation
for a classified symlink, otherwise passes the original source pathname to the
platform copier. No opened source descriptor binds this decision to the use.
The vulnerability requires a swap after that decision; a symlink already seen
by the check is not evidence of the bug. Intentional dereference mode is also
not the vulnerable contract.

The seven confirmed source-qualified functions have branch-specific reasons in
their records. This includes Linux direct File::open sites at 61,135,185,247 and
its own delegated content-copy sites at 79,298,314,333. Stream copying participates
only when the saved type is FIFO/device and content copying is selected; the
stream branch must not be claimed for an initially regular source.

Additional source-open inventory and dispositions:

- linux.rs check_for_data:90 opens the pathname, may read a temporary probe buffer,
  and returns data/size/allocation indicators. check_sparse_detection:117 opens
  it for metadata. These probes influence copy-method selection but do not send
  that descriptor or its contents to the destination. A later data-copy open is
  a separate use. Neither probe is mapped merely for opening the source; their
  inclusion in later hardening is not independent exfiltration evidence.
- other_unix.rs:45 is an explicit source open in the stream-copy branch and
  transfers bytes from that descriptor; line 66 delegates regular copying.
- macos.rs:95 is an explicit source open in the stream fallback and transfers
  bytes from that descriptor; line 113 delegates regular copying. Its clonefile
  calls at 64 and 78 are pathname-based native operations, whose complete
  historical symlink semantics are not established by the source text alone.
- other.rs:37 only delegates to fs::copy. platform/mod.rs selects this file for
  non-Unix targets. It is NOT other_unix.rs. The prior confirmed other.rs record
  is withdrawn pending native-platform evidence, rather than extrapolating the
  Linux O_NOFOLLOW observation to it.
- cp.rs's backup fs::copy at 1810 reads the destination for backup, not the source
  in the no-dereference check/use sequence. AttrOnly opens only the destination.
  copy_link reads a link target as a link, and hard-link/FIFO/socket handling does
  not itself open the checked source for this content-transfer mechanism.
- buf_copy receives already-open descriptors here; it is not an additional
  pathname-check/open site. Dispatcher helpers and mode-propagation changes are
  not counted as independently vulnerable locations.

Platform-specific identities are preserved separately. The two added Unix
stream locations are source-supported instances of the disclosed mechanism,
not inferred from later patch membership or from a measured call graph.
Exhaustiveness remains unproven for the opaque native/delegated platform cases;
mapping_status remains unresolved, with seven confirmed partial locations.
""",
    35361: """## Narrow pre-measurement audit

[PR 10582](https://github.com/uutils/coreutils/pull/10582) changes the error path
directly inside fn mknod(file_name: &str, config: Config) -> i32: after SELinux
context application fails, remove_dir is replaced by remove_file. The vulnerable
release has the faulty cleanup in that same function. The added regression test
is corroboration, not a vulnerable function. Mapping to mknod remains verified.

Whether label application becomes atomic is a separate remediation-history
question. It does not make the function identity or mapping status unresolved.
""",
}
