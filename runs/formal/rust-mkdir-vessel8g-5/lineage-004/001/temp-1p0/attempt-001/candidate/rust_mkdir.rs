use std::ffi::OsString;
use std::io::Write;
use std::os::unix::ffi::OsStrExt;
use std::os::unix::fs::PermissionsExt;
use std::process;

fn os_error_str(e: &std::io::Error) -> String {
    let s = e.to_string();
    if let Some(idx) = s.find(" (os error ") {
        s[..idx].to_string()
    } else {
        s
    }
}

fn mkdir_p(operand: &std::ffi::OsStr) -> Result<(), Vec<u8>> {
    fn err_msg(operand: &std::ffi::OsStr, desc: &str) -> Vec<u8> {
        let mut msg = b"mkdir: cannot create directory '".to_vec();
        msg.extend_from_slice(operand.as_bytes());
        msg.extend_from_slice(b"': ".as_slice());
        msg.extend_from_slice(desc.as_bytes());
        msg.extend_from_slice(b"\n".as_slice());
        msg
    }

    let bytes = operand.as_bytes();
    if bytes.is_empty() {
        return Err(err_msg(operand, "No such file or directory"));
    }

    let is_absolute = bytes[0] == b'/';

    // Split operand into name segments, filtering empty (from repeated
    // slashes) and dot components. Resolve ".." by popping the previous
    // segment when possible.
    let mut segments: Vec<&[u8]> = Vec::new();
    for seg in bytes.split(|&b| b == b'/') {
        if seg.is_empty() || seg == b"." {
            continue;
        }
        if seg == b".." {
            if let Some(last) = segments.last() {
                if *last != b".." {
                    segments.pop();
                    continue;
                }
            }
        }
        segments.push(seg);
    }

    // Path resolved to "." or "/" — already a directory, nothing to do.
    if segments.is_empty() {
        return Ok(());
    }

    // Build each intermediate path as an explicit byte vector with '/'
    // separators inserted manually.
    let mut current_bytes: Vec<u8> = Vec::new();
    if is_absolute {
        current_bytes.push(b'/');
    }

    for (i, seg) in segments.iter().enumerate() {
        if !current_bytes.is_empty() && current_bytes.last().unwrap() != &b'/' {
            current_bytes.push(b'/');
        }
        current_bytes.extend_from_slice(*seg);

        let is_last = (i + 1) == segments.len();
        let path = std::ffi::OsString::from_vec(current_bytes.clone());

        match std::fs::symlink_metadata(&path) {
            Ok(meta) => {
                let ft = meta.file_type();
                if ft.is_dir() {
                    continue;
                }
                if ft.is_symlink() {
                    if let Ok(m) = std::fs::metadata(&path) {
                        if m.is_dir() {
                            continue;
                        }
                    }
                }
                if is_last {
                    return Err(err_msg(operand, "File exists"));
                } else {
                    return Err(err_msg(operand, "Not a directory"));
                }
            }
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
                if let Err(e) = std::fs::create_dir(&path) {
                    return Err(err_msg(operand, &os_error_str(&e)));
                }
                if !is_last {
                    if let Ok(meta) = std::fs::metadata(&path) {
                        let mode = meta.permissions().mode();
                        let _ = std::fs::set_permissions(
                            &path,
                            std::fs::Permissions::from_mode(mode | 0o300),
                        );
                    }
                }
                continue;
            }
            Err(e) => {
                return Err(err_msg(operand, &os_error_str(&e)));
            }
        }
    }

    Ok(())
}

fn main() {
    let args: Vec<OsString> = std::env::args_os().skip(1).collect();

    let mut operands: Vec<OsString> = Vec::new();
    let mut after_ddash = false;
    let mut parents = false;

    for arg in &args {
        if after_ddash {
            operands.push(arg.clone());
            continue;
        }
        let bytes = arg.as_bytes();
        if bytes == b"--" {
            after_ddash = true;
            continue;
        }
        if bytes == b"-" {
            operands.push(arg.clone());
            continue;
        }
        if bytes[0] == b'-' && bytes.len() > 1 {
            if bytes == b"-p" || bytes == b"--parents" {
                parents = true;
                continue;
            }
            let stderr = std::io::stderr();
            let mut lock = stderr.lock();
            if bytes.len() >= 3 && bytes[1] == b'-' {
                let _ = lock.write_all(b"mkdir: unrecognized option '");
                let _ = lock.write_all(bytes);
                let _ = lock.write_all(b"'\n");
            } else {
                let _ = lock.write_all(b"mkdir: invalid option -- '");
                let _ = lock.write_all(&[bytes[1]]);
                let _ = lock.write_all(b"'\n");
            }
            let _ = lock.write_all(b"Try 'mkdir --help' for more information.\n");
            process::exit(1);
        }
        operands.push(arg.clone());
    }

    if operands.is_empty() {
        let stderr = std::io::stderr();
        let mut lock = stderr.lock();
        let _ = lock.write_all(b"mkdir: missing operand\n");
        let _ = lock.write_all(b"Try 'mkdir --help' for more information.\n");
        process::exit(1);
    }

    let mut any_failed = false;
    for operand in &operands {
        if parents {
            if let Err(msg) = mkdir_p(operand) {
                let stderr = std::io::stderr();
                let mut lock = stderr.lock();
                let _ = lock.write_all(&msg);
                any_failed = true;
            }
        } else {
            if let Err(e) = std::fs::create_dir(operand) {
                let err_msg = os_error_str(&e);
                let stderr = std::io::stderr();
                let mut lock = stderr.lock();
                let _ = lock.write_all(b"mkdir: cannot create directory '");
                let _ = lock.write_all(operand.as_bytes());
                let _ = lock.write_all(b"': ");
                let _ = lock.write_all(err_msg.as_bytes());
                let _ = lock.write_all(b"\n");
                any_failed = true;
            }
        }
    }

    if any_failed {
        process::exit(1);
    }
}
