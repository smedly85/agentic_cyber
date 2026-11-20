use std::ffi::OsString;
use std::io::Write;
use std::os::unix::ffi::OsStrExt;
use std::process;

fn os_error_str(e: &std::io::Error) -> String {
    let s = e.to_string();
    if let Some(idx) = s.find(" (os error ") {
        s[..idx].to_string()
    } else {
        s
    }
}

fn main() {
    let args: Vec<OsString> = std::env::args_os().skip(1).collect();

    let mut operands: Vec<OsString> = Vec::new();
    let mut after_ddash = false;

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

    if any_failed {
        process::exit(1);
    }
}
