use std::ffi::OsString;
use std::os::unix::ffi::OsStrExt;

fn errno_string(e: &std::io::Error) -> String {
    let s = e.to_string();
    if let Some(idx) = s.rfind(" (os error ") {
        s[..idx].to_string()
    } else {
        s
    }
}

fn main() {
    let args: Vec<OsString> = std::env::args_os().skip(1).collect();

    let mut operands: Vec<OsString> = Vec::new();
    let mut option_terminated = false;

    for arg in &args {
        if !option_terminated {
            let bytes = arg.as_bytes();
            if bytes.len() > 1 && bytes[0] == b'-' {
                if bytes == b"--" {
                    option_terminated = true;
                    continue;
                }
                if bytes.len() == 2 || bytes[1] != b'-' {
                    let c = bytes[1] as char;
                    eprintln!("mkdir: invalid option -- '{}'", c);
                    eprintln!("Try 'mkdir --help' for more information.");
                } else {
                    let word = String::from_utf8_lossy(arg.as_bytes());
                    eprintln!("mkdir: unrecognized option '{}'", word);
                    eprintln!("Try 'mkdir --help' for more information.");
                }
                std::process::exit(1);
            }
        }
        operands.push(arg.clone());
    }

    if operands.is_empty() {
        eprintln!("mkdir: missing operand");
        eprintln!("Try 'mkdir --help' for more information.");
        std::process::exit(1);
    }

    let mut had_error = false;
    for op in &operands {
        if let Err(e) = std::fs::create_dir(op) {
            eprintln!(
                "mkdir: cannot create directory '{}': {}",
                op.to_string_lossy(),
                errno_string(&e)
            );
            had_error = true;
        }
    }

    std::process::exit(if had_error { 1 } else { 0 });
}
