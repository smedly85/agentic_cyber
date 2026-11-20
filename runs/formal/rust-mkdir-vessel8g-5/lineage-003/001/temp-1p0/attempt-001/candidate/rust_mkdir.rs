use std::io::Write;
use std::os::unix::ffi::OsStrExt;
use std::os::unix::fs::DirBuilderExt;
use std::os::unix::fs::PermissionsExt;

fn main() {
    let args: Vec<std::ffi::OsString> = std::env::args_os().skip(1).collect();

    let mut seen_dd = false;
    let mut operands: Vec<std::ffi::OsString> = Vec::new();
    let mut parents = false;

    for arg in &args {
        let bytes = arg.as_bytes();
        if !seen_dd {
            if bytes == b"--" {
                seen_dd = true;
            } else if bytes == b"-" {
                operands.push(arg.clone());
            } else if bytes == b"-p" {
                parents = true;
            } else if bytes == b"--parents" {
                parents = true;
            } else if bytes.first() == Some(&b'-') {
                // Unknown option: emit GNU-style diagnostic and exit 1.
                let mut out: Vec<u8> = Vec::new();
                if bytes.len() > 1 && bytes[1] == b'-' {
                    // Long option (e.g. --foo)
                    out.extend_from_slice(b"mkdir: unrecognized option '");
                    out.extend_from_slice(bytes);
                    out.extend_from_slice(b"'\nTry 'mkdir --help' for more information.\n");
                } else {
                    // Short option (e.g. -x): report the single offending byte.
                    out.extend_from_slice(b"mkdir: invalid option -- '");
                    out.push(bytes[1]);
                    out.extend_from_slice(b"'\nTry 'mkdir --help' for more information.\n");
                }
                let stderr = std::io::stderr();
                let mut lock = stderr.lock();
                let _ = lock.write_all(&out);
                std::process::exit(1);
            } else {
                operands.push(arg.clone());
            }
        } else {
            // After "--" every argument is a literal operand.
            operands.push(arg.clone());
        }
    }

    if operands.is_empty() {
        let msg = b"mkdir: missing operand\nTry 'mkdir --help' for more information.\n";
        let stderr = std::io::stderr();
        let mut lock = stderr.lock();
        let _ = lock.write_all(msg);
        std::process::exit(1);
    }

    let mut any_failed = false;
    for operand in &operands {
        let path = std::path::Path::new(operand);
        let result: Result<(), std::io::Error> = if parents {
            create_parents(path)
        } else {
            std::fs::create_dir(path).map(|()| ())
        };

        if let Err(e) = result {
            any_failed = true;
            let err_msg = os_error_message(&e);
            let mut out: Vec<u8> = Vec::new();
            out.extend_from_slice(b"mkdir: cannot create directory '");
            out.extend_from_slice(operand.as_bytes());
            out.extend_from_slice(b"': ");
            out.extend_from_slice(err_msg.as_bytes());
            out.extend_from_slice(b"\n");
            let stderr = std::io::stderr();
            let mut lock = stderr.lock();
            let _ = lock.write_all(&out);
        }
    }

    if any_failed {
        std::process::exit(1);
    }
}

/// Extract the human-readable errno string from an `io::Error`.
/// Rust's `Display` for OS errors is `"<message> (os error <code>)"`;
/// strip the suffix to match `strerror()` wording.
fn os_error_message(e: &std::io::Error) -> String {
    if e.raw_os_error().is_some() {
        let s = e.to_string();
        if let Some(pos) = s.rfind(" (os error ") {
            return s[..pos].to_string();
        }
        s
    } else {
        e.to_string()
    }
}

/// Lexically normalize a path: remove `.` components, resolve `..` by
/// popping the previous component, collapse redundant slashes.
/// Does not touch the filesystem.
fn normalize_path(path: &std::path::Path) -> std::path::PathBuf {
    let mut parts: Vec<std::ffi::OsString> = Vec::new();
    let is_absolute = path.is_absolute();
    for comp in path.components() {
        match comp {
            std::path::Component::CurDir => {}
            std::path::Component::ParentDir => { parts.pop(); }
            std::path::Component::Normal(c) => { parts.push(c.to_os_string()); }
            std::path::Component::RootDir => {}
            _ => {}
        }
    }
    let mut out = std::path::PathBuf::new();
    if is_absolute {
        out.push("/");
    }
    for p in &parts {
        out.push(p);
    }
    out
}

/// Create all missing intermediate directories plus the final directory.
/// Existing directories (or symlinks resolving to directories) are accepted.
/// Existing non-directories are an error (ENOTDIR).
fn create_parents(path: &std::path::Path) -> Result<(), std::io::Error> {
    // Empty-string operand: let the OS reject it.
    if path.as_os_str().is_empty() {
        return std::fs::create_dir(path).map(|()| ());
    }

    let normalized = normalize_path(path);

    // If normalization yields just "/" (root) or an empty relative path (i.e.
    // the operand was "." or "./" or "/"), the target already exists as a dir.
    if normalized == std::path::Path::new("/") || normalized.as_os_str().is_empty() {
        return Ok(());
    }

    let components: Vec<std::path::Component> = normalized.components().collect();
    let n = components.len();
    let mut prefix = std::path::PathBuf::new();

    for (i, comp) in components.iter().enumerate() {
        match comp {
            std::path::Component::RootDir => {
                prefix.push("/");
                continue;
            }
            std::path::Component::Normal(c) => {
                prefix.push(c);
                let is_final = i == n - 1;

                match std::fs::symlink_metadata(&prefix) {
                    Ok(meta) => {
                        if meta.is_dir() {
                            continue;
                        }
                        if meta.file_type().is_symlink() {
                            // Follow the symlink to decide.
                            match std::fs::metadata(&prefix) {
                                Ok(m2) if m2.is_dir() => continue,
                                _ => {
                                    return Err(std::io::Error::from_raw_os_error(
                                        20, // ENOTDIR
                                    ));
                                }
                            }
                        }
                        // Regular non-directory file.
                        if is_final {
                            return Err(std::io::Error::from_raw_os_error(17)); // EEXIST
                        }
                        return Err(std::io::Error::from_raw_os_error(20)); // ENOTDIR
                    }
                    Err(_) => {
                        // Does not exist: create it.
                        std::fs::DirBuilder::new().mode(0o777).create(&prefix)?;
                        if !is_final {
                            // Ensure owner has write + search (execute) even
                            // if the umask stripped them.
                            let m = std::fs::metadata(&prefix)?;
                            let cur = m.permissions().mode();
                            let want = cur | 0o300;
                            if cur != want {
                                std::fs::set_permissions(
                                    &prefix,
                                    std::fs::Permissions::from_mode(want),
                                )?;
                            }
                        }
                    }
                }
            }
            _ => {}
        }
    }

    Ok(())
}
