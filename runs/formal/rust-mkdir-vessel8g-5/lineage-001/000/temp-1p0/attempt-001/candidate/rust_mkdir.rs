use std::env;
use std::ffi::OsString;
use std::fs;
use std::io::Write;
use std::process;

fn errno_to_str(errno: i32) -> &'static str {
    match errno {
        2 => "No such file or directory",
        13 => "Permission denied",
        17 => "File exists",
        20 => "Not a directory",
        30 => "Read-only file system",
        36 => "File name too long",
        40 => "Too many levels of symbolic links",
        _ => "Unknown error",
    }
}

fn die_invalid_option(arg: &OsString) -> ! {
    let bytes = arg.as_encoded_bytes();
    let mut err = std::io::stderr();
    if bytes.len() > 2 && bytes.starts_with(b"--") {
        let _ = write!(err, "mkdir: unrecognized option '");
        let _ = err.write_all(bytes);
        let _ = writeln!(err, "'");
    } else {
        let c = bytes.get(1).copied().unwrap_or(b'?') as char;
        let _ = writeln!(err, "mkdir: invalid option -- '{}'", c);
    }
    let _ = writeln!(err, "Try 'mkdir --help' for more information.");
    process::exit(1);
}

fn die_missing_operand() -> ! {
    let mut err = std::io::stderr();
    let _ = writeln!(err, "mkdir: missing operand");
    let _ = writeln!(err, "Try 'mkdir --help' for more information.");
    process::exit(1);
}

fn main() {
    let args: Vec<OsString> = env::args_os().skip(1).collect();
    let mut operands: Vec<OsString> = Vec::new();
    let mut after_ddash = false;

    for arg in &args {
        let b = arg.as_encoded_bytes();
        if after_ddash {
            operands.push(arg.clone());
        } else if b == b"--" {
            after_ddash = true;
        } else if b.len() > 1 && b[0] == b'-' {
            die_invalid_option(arg);
        } else {
            operands.push(arg.clone());
        }
    }

    if operands.is_empty() {
        die_missing_operand();
    }

    let mut all_ok = true;

    for op in &operands {
        if let Err(e) = fs::create_dir(op) {
            all_ok = false;
            let errno = e.raw_os_error().unwrap_or(-1);
            let msg = errno_to_str(errno);
            let path = op.as_encoded_bytes();
            let mut err = std::io::stderr().lock();
            let _ = write!(err, "mkdir: cannot create directory '");
            let _ = err.write_all(path);
            let _ = writeln!(err, "': {}", msg);
        }
    }

    process::exit(if all_ok { 0 } else { 1 });
}
