use std::ffi::{OsStr, OsString};
use std::fs;
use std::os::unix::ffi::OsStrExt;
use std::path::{Path, PathBuf};
use std::process::ExitCode;

fn main() -> ExitCode {
    let args: Vec<OsString> = std::env::args_os().collect();

    // Parse arguments: options before --, operands after --
    let mut operands: Vec<PathBuf> = Vec::new();
    let mut after_ddash = false;

    for arg in args.iter().skip(1) {
        if !after_ddash {
            let bytes = arg.as_bytes();
            if bytes == b"--" {
                after_ddash = true;
                continue;
            }
            if bytes.len() > 1 && bytes[0] == b'-' {
                eprintln!(
                    "rust_mv: unknown option '{}'",
                    String::from_utf8_lossy(bytes)
                );
                return ExitCode::from(1);
            }
        }
        operands.push(PathBuf::from(arg));
    }

    if operands.len() < 2 {
        eprintln!("rust_mv: missing operand(s)");
        return ExitCode::from(1);
    }

    // Determine source-destination pairs
    let n = operands.len();
    let pairs: Vec<(PathBuf, PathBuf)>;

    if n == 2 {
        let source = &operands[0];
        let dest = &operands[1];

        let effective_dest = if let Ok(meta) = fs::symlink_metadata(dest) {
            if meta.is_dir() {
                let base = source.file_name().unwrap_or(OsStr::new("."));
                dest.join(base)
            } else {
                dest.clone()
            }
        } else {
            dest.clone()
        };

        pairs = vec![(source.clone(), effective_dest)];
    } else {
        let dir = &operands[n - 1];
        match fs::symlink_metadata(dir) {
            Ok(meta) if meta.is_dir() => {}
            _ => {
                eprintln!(
                    "rust_mv: target '{}' is not a directory",
                    dir.to_string_lossy()
                );
                return ExitCode::from(1);
            }
        }

        pairs = (0..n - 1)
            .map(|i| {
                let source = &operands[i];
                let base = source.file_name().unwrap_or(OsStr::new("."));
                (source.clone(), dir.join(base))
            })
            .collect();
    }

    // Execute moves in order, continuing on failure
    let mut any_failed = false;
    for (source, dest) in &pairs {
        if let Err(msg) = move_path(source, dest) {
            eprintln!("rust_mv: {}", msg);
            any_failed = true;
        }
    }

    if any_failed {
        ExitCode::from(1)
    } else {
        ExitCode::SUCCESS
    }
}

fn move_path(source: &Path, destination: &Path) -> Result<(), String> {
    let src_meta = fs::symlink_metadata(source)
        .map_err(|e| format!("cannot stat '{}': {}", source.display(), e))?;

    let src_is_dir = src_meta.is_dir();

    match fs::symlink_metadata(destination) {
        Ok(dst_meta) => {
            let dst_is_dir = dst_meta.is_dir();

            // Identity and ancestor checks via canonicalization
            if let (Ok(src_canon), Ok(dst_canon)) =
                (fs::canonicalize(source), fs::canonicalize(destination))
            {
                if src_canon == dst_canon {
                    return Err(format!(
                        "'{}' and '{}' are the same file",
                        source.display(),
                        destination.display()
                    ));
                }
                if src_is_dir && dst_canon.starts_with(&src_canon) {
                    return Err(format!(
                        "cannot move '{}' into a subdirectory of itself",
                        source.display()
                    ));
                }
            }

            // Type compatibility at the effective destination
            if !src_is_dir && dst_is_dir {
                return Err(format!(
                    "cannot overwrite directory '{}' with non-directory '{}'",
                    destination.display(),
                    source.display()
                ));
            }
            if src_is_dir && !dst_is_dir {
                return Err(format!(
                    "cannot overwrite non-directory '{}' with directory '{}'",
                    destination.display(),
                    source.display()
                ));
            }
            if src_is_dir && dst_is_dir {
                if let Ok(mut reader) = fs::read_dir(destination) {
                    if reader.next().is_some() {
                        return Err(format!(
                            "target '{}' is a non-empty directory",
                            destination.display()
                        ));
                    }
                }
            }
        }
        Err(_) => {
            // Destination does not exist; still guard against moving a
            // directory into its own subtree.
            if src_is_dir {
                if let Ok(src_canon) = fs::canonicalize(source) {
                    let mut ancestor = destination.to_path_buf();
                    while ancestor.as_os_str().len() > 0 {
                        if let Ok(a_canon) = fs::canonicalize(&ancestor) {
                            if a_canon == src_canon || a_canon.starts_with(&src_canon) {
                                return Err(format!(
                                    "cannot move '{}' into a subdirectory of itself",
                                    source.display()
                                ));
                            }
                            break;
                        }
                        ancestor = match ancestor.parent() {
                            Some(p) => p.to_path_buf(),
                            None => break,
                        };
                    }
                }
            }
        }
    }

    fs::rename(source, destination).map_err(|e| {
        format!(
            "cannot move '{}' to '{}': {}",
            source.display(),
            destination.display(),
            e
        )
    })
}
