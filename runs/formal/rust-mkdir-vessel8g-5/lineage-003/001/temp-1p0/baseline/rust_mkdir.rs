use std::io::Write;
use std::os::unix::ffi::OsStrExt;

fn main() {
    let args: Vec<std::ffi::OsString> = std::env::args_os().skip(1).collect();

    let mut seen_dd = false;
    let mut operands: Vec<std::ffi::OsString> = Vec::new();

    for arg in &args {
        let bytes = arg.as_bytes();
        if !seen_dd {
            if bytes == b"--" {
                seen_dd = true;
            } else if bytes == b"-" {
                operands.push(arg.clone());
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
        if let Err(e) = std::fs::create_dir(path) {
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
