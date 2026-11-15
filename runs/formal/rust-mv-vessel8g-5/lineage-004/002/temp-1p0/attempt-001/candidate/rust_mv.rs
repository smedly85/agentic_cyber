use std::ffi::{OsStr, OsString};
use std::io::BufRead;
use std::os::unix::ffi::OsStrExt;
use std::path::{Path, PathBuf};
use std::process::ExitCode;

fn display_os(os: &OsStr) -> String {
    os.to_string_lossy().into_owned()
}

fn is_option(arg: &OsStr) -> bool {
    let bytes = arg.as_bytes();
    bytes.len() > 1 && bytes[0] == b'-'
}

fn move_path(src: &Path, dest: &Path) -> std::io::Result<()> {
    std::fs::rename(src, dest)
}

fn perform_move(src: &Path, dest: &Path, src_display: &OsStr, prompt: bool) -> bool {
    let src_meta = match std::fs::symlink_metadata(src) {
        Ok(m) => m,
        Err(e) => {
            eprintln!("rust_mv: {}: {}", display_os(src_display), e);
            return false;
        }
    };

    let src_is_dir = src_meta.file_type().is_dir();
    let dest_exists = std::fs::symlink_metadata(dest).is_ok();

    // Identical source/destination check
    let src_canon = std::fs::canonicalize(src);
    let dest_canon = std::fs::canonicalize(dest);
    if let (Ok(sc), Ok(dc)) = (&src_canon, &dest_canon) {
        if sc == dc {
            eprintln!(
                "rust_mv: '{}' and '{}' are the same file",
                display_os(src_display),
                display_os(dest.as_os_str())
            );
            return false;
        }
    }

    if src_is_dir {
        // Reject moving a directory into itself or its own subtree
        if let Ok(sc) = &src_canon {
            let dest_check: PathBuf = if dest_exists {
                match &dest_canon {
                    Ok(dc) => dc.clone(),
                    Err(_) => {
                        eprintln!(
                            "rust_mv: cannot determine path for '{}'",
                            display_os(dest.as_os_str())
                        );
                        return false;
                    }
                }
            } else {
                let parent = dest.parent().unwrap_or(Path::new("."));
                let parent = if parent.as_os_str().is_empty() {
                    Path::new(".")
                } else {
                    parent
                };
                match std::fs::canonicalize(parent) {
                    Ok(p) => p,
                    Err(e) => {
                        eprintln!(
                            "rust_mv: cannot move '{}' to '{}': {}",
                            display_os(src_display),
                            display_os(dest.as_os_str()),
                            e
                        );
                        return false;
                    }
                }
            };
            if dest_check == *sc || dest_check.starts_with(sc) {
                eprintln!(
                    "rust_mv: cannot move directory '{}' into itself",
                    display_os(src_display)
                );
                return false;
            }
        }

        // Destination exists: must be a directory and must be empty
        if dest_exists {
            match std::fs::symlink_metadata(dest) {
                Ok(dm) => {
                    if !dm.file_type().is_dir() {
                        eprintln!(
                            "rust_mv: cannot overwrite non-directory '{}' with directory '{}'",
                            display_os(dest.as_os_str()),
                            display_os(src_display)
                        );
                        return false;
                    }
                    match std::fs::read_dir(dest) {
                        Ok(mut entries) => {
                            if entries.next().is_some() {
                                eprintln!(
                                    "rust_mv: cannot move directory '{}' into non-empty directory '{}'",
                                    display_os(src_display),
                                    display_os(dest.as_os_str())
                                );
                                return false;
                            }
                        }
                        Err(e) => {
                            eprintln!(
                                "rust_mv: cannot read directory '{}': {}",
                                display_os(dest.as_os_str()),
                                e
                            );
                            return false;
                        }
                    }
                }
                Err(e) => {
                    eprintln!(
                        "rust_mv: cannot stat '{}': {}",
                        display_os(dest.as_os_str()),
                        e
                    );
                    return false;
                }
            }
        }
    } else {
        // Source is not a directory: destination must not be a directory
        if dest_exists {
            if let Ok(dm) = std::fs::symlink_metadata(dest) {
                if dm.file_type().is_dir() {
                    eprintln!(
                        "rust_mv: cannot overwrite directory '{}' with non-directory '{}'",
                        display_os(dest.as_os_str()),
                        display_os(src_display)
                    );
                    return false;
                }
            }
        }
    }

    if dest_exists && prompt {
        eprint!("rust_mv: overwrite {}? ", display_os(dest.as_os_str()));
        let mut line = String::new();
        let mut stdin = std::io::stdin().lock();
        if stdin.read_line(&mut line).is_err() {
            return false;
        }
        match line.bytes().next() {
            Some(b'y') | Some(b'Y') => {}
            _ => return false,
        }
    }

    // Perform the atomic rename
    if let Err(e) = move_path(src, dest) {
        eprintln!(
            "rust_mv: cannot move '{}' to '{}': {}",
            display_os(src_display),
            display_os(dest.as_os_str()),
            e
        );
        return false;
    }

    true
}

fn main() -> ExitCode {
    let args: Vec<OsString> = std::env::args_os().skip(1).collect();

    // Parse: options before --, literal operands after --
    let mut operands: Vec<OsString> = Vec::new();
    let mut prompt = false;
    let mut after_ddash = false;
    for arg in &args {
        if !after_ddash && arg.as_bytes() == b"--" {
            after_ddash = true;
            continue;
        }
        if !after_ddash && is_option(arg) {
            let bytes = arg.as_bytes();
            if bytes == b"-f" || bytes == b"--force" {
                prompt = false;
                continue;
            }
            if bytes == b"-i" || bytes == b"--interactive" {
                prompt = true;
                continue;
            }
            eprintln!("rust_mv: unknown option: {}", display_os(arg));
            return ExitCode::from(1);
        }
        operands.push(arg.clone());
    }

    if operands.len() < 2 {
        eprintln!("rust_mv: missing required operand");
        return ExitCode::from(1);
    }

    let mut any_failed = false;

    if operands.len() == 2 {
        // Single source to single destination
        let src = Path::new(&operands[0]);
        let dest_raw = Path::new(&operands[1]);

        let effective_dest: PathBuf = if std::fs::symlink_metadata(dest_raw)
            .map(|m| m.file_type().is_dir())
            .unwrap_or(false)
        {
            match src.file_name() {
                Some(fn_) => dest_raw.join(fn_),
                None => {
                    eprintln!(
                        "rust_mv: cannot determine file name for source: {}",
                        display_os(&operands[0])
                    );
                    return ExitCode::from(1);
                }
            }
        } else {
            dest_raw.to_path_buf()
        };

        if !perform_move(src, &effective_dest, &operands[0], prompt) {
            any_failed = true;
        }
    } else {
        // Multi-source: last operand must be an existing directory
        let last_os = &operands[operands.len() - 1];
        let last = Path::new(last_os);
        match std::fs::symlink_metadata(last) {
            Ok(m) if m.file_type().is_dir() => {}
            _ => {
                eprintln!(
                    "rust_mv: {}: target directory does not exist or is not a directory",
                    display_os(last_os)
                );
                return ExitCode::from(1);
            }
        }

        for i in 0..operands.len() - 1 {
            let src = Path::new(&operands[i]);
            let file_name = match src.file_name() {
                Some(fn_) => fn_,
                None => {
                    eprintln!(
                        "rust_mv: cannot determine file name for source: {}",
                        display_os(&operands[i])
                    );
                    any_failed = true;
                    continue;
                }
            };
            let effective_dest = last.join(file_name);

            if !perform_move(src, &effective_dest, &operands[i], prompt) {
                any_failed = true;
            }
        }
    }

    if any_failed {
        ExitCode::from(1)
    } else {
        ExitCode::SUCCESS
    }
}
