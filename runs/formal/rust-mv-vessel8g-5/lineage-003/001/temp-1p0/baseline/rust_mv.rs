use std::ffi::{OsStr, OsString};
use std::os::unix::ffi::OsStrExt;
use std::path::{Path, PathBuf};
use std::process::ExitCode;

/// Core filesystem move operation: atomically renames src to dst.
fn move_path(src: &Path, dst: &Path) -> std::io::Result<()> {
    std::fs::rename(src, dst)
}

/// True if `path` exists (following symlinks) and is a directory.
fn is_directory(path: &Path) -> bool {
    path.metadata().map(|m| m.is_dir()).unwrap_or(false)
}

/// True if `child` is lexically the same as or a proper descendant of `parent`.
fn is_same_or_descendant(parent: &Path, child: &Path) -> bool {
    let p = parent.as_os_str().as_bytes();
    let c = child.as_os_str().as_bytes();
    if c.len() < p.len() {
        return false;
    }
    if c[..p.len()] != *p {
        return false;
    }
    c.len() == p.len() || c[p.len()] == b'/'
}

fn do_move(src: &Path, dst: &Path) -> Result<(), String> {
    // Source must exist (lstat: does not follow symlinks).
    let src_meta = match src.symlink_metadata() {
        Ok(m) => m,
        Err(_) => {
            return Err(format!(
                "mv: cannot stat '{}': No such file or directory",
                src.to_string_lossy()
            ))
        }
    };

    let src_is_dir = src_meta.is_dir();

    // Identical source and destination.
    if src.as_os_str() == dst.as_os_str() {
        return Err(format!(
            "mv: '{}' and '{}' are the same file",
            src.to_string_lossy(),
            dst.to_string_lossy()
        ));
    }
    // Canonical comparison catches cases like "dir" vs "./dir".
    if let (Ok(cs), Ok(cd)) = (std::fs::canonicalize(src), std::fs::canonicalize(dst)) {
        if cs == cd {
            return Err(format!(
                "mv: '{}' and '{}' are the same file",
                src.to_string_lossy(),
                dst.to_string_lossy()
            ));
        }
    }

    // A directory cannot be moved into itself or a proper descendant of itself.
    if src_is_dir && is_same_or_descendant(src, dst) {
        return Err(format!(
            "mv: cannot move directory '{}' into itself or its subdirectory '{}'",
            src.to_string_lossy(),
            dst.to_string_lossy()
        ));
    }

    // Type-compatibility pre-checks for better diagnostics.
    // The kernel's rename(2) is atomic and will also reject these, but we
    // diagnose them explicitly per the spec.
    if let Ok(dst_meta) = dst.symlink_metadata() {
        let dst_is_dir = dst_meta.is_dir();
        let dst_is_symlink = dst_meta.file_type().is_symlink();

        if src_is_dir {
            // Directory source: destination must not be a non-directory.
            if !dst_is_dir {
                if dst_is_symlink {
                    // Resolve the symlink to see what it points to.
                    if let Ok(resolved) = dst.metadata() {
                        if resolved.is_dir() {
                            // Symlink to directory: rename(2) will handle it
                            // (succeeds if target is empty, ENOTEMPTY otherwise).
                            // Fall through to rename.
                        } else {
                            return Err(format!(
                                "mv: cannot overwrite non-directory '{}' with directory '{}'",
                                dst.to_string_lossy(),
                                src.to_string_lossy()
                            ));
                        }
                    }
                    // Broken symlink: rename(2) will replace it. Fall through.
                } else {
                    return Err(format!(
                        "mv: cannot overwrite non-directory '{}' with directory '{}'",
                        dst.to_string_lossy(),
                        src.to_string_lossy()
                    ));
                }
            }
        } else {
            // Non-directory source: destination must not be a directory.
            if dst_is_dir {
                return Err(format!(
                    "mv: cannot overwrite directory '{}' with non-directory '{}'",
                    dst.to_string_lossy(),
                    src.to_string_lossy()
                ));
            }
            if dst_is_symlink {
                if let Ok(resolved) = dst.metadata() {
                    if resolved.is_dir() {
                        return Err(format!(
                            "mv: cannot overwrite directory '{}' with non-directory '{}'",
                            dst.to_string_lossy(),
                            src.to_string_lossy()
                        ));
                    }
                }
                // Symlink to file or broken symlink: rename(2) replaces the link.
            }
        }
    }

    // Perform the atomic rename.
    match move_path(src, dst) {
        Ok(()) => Ok(()),
        Err(e) => Err(format!(
            "mv: cannot move '{}' to '{}': {}",
            src.to_string_lossy(),
            dst.to_string_lossy(),
            e
        )),
    }
}

fn main() -> ExitCode {
    let args: Vec<OsString> = std::env::args_os().skip(1).collect();

    // Phase 1: separate options from operands.
    // Before "--": "-" alone is a filename; "-X" or "--foo" is an unknown option.
    // After "--": every token is a literal operand.
    let mut operands: Vec<OsString> = Vec::new();
    let mut after_ddash = false;

    for arg in &args {
        if !after_ddash {
            let b = arg.as_bytes();
            if b == b"--" {
                after_ddash = true;
                continue;
            }
            if b.len() > 1 && b[0] == b'-' {
                eprintln!(
                    "mv: unknown option '{}'",
                    arg.to_string_lossy()
                );
                return ExitCode::from(1);
            }
        }
        operands.push(arg.clone());
    }

    // Phase 2: validate operand count.
    if operands.len() < 2 {
        eprintln!("mv: missing operand");
        return ExitCode::from(1);
    }

    let n = operands.len();
    let multi_source = n > 2;

    // Phase 3: for multi-source, the last operand must be an existing directory.
    if multi_source {
        let dir = Path::new(&operands[n - 1]);
        if !is_directory(dir) {
            eprintln!(
                "mv: target '{}' is not a directory",
                dir.to_string_lossy()
            );
            return ExitCode::from(1);
        }
    }

    // Phase 4: process each source in operand order.
    let mut any_failed = false;
    let num_sources = if multi_source { n - 1 } else { 1 };

    for i in 0..num_sources {
        let src = Path::new(&operands[i]);

        // Determine effective destination.
        let dst: PathBuf = if multi_source {
            let dir = Path::new(&operands[n - 1]);
            let base = src.file_name().unwrap_or(OsStr::new(""));
            dir.join(base)
        } else {
            let dest = Path::new(&operands[1]);
            if is_directory(dest) {
                let base = src.file_name().unwrap_or(OsStr::new(""));
                dest.join(base)
            } else {
                dest.to_path_buf()
            }
        };

        // Attempt the move; on failure diagnose and continue.
        if let Err(msg) = do_move(src, &dst) {
            eprintln!("{}", msg);
            any_failed = true;
        }
    }

    if any_failed {
        ExitCode::from(1)
    } else {
        ExitCode::SUCCESS
    }
}
