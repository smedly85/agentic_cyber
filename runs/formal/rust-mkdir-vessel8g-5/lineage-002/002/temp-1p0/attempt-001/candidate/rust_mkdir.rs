use std::ffi::OsString;
use std::io::Write;
use std::os::unix::ffi::OsStrExt;
use std::path::Path;
use std::process::ExitCode;

fn main() -> ExitCode {
    let args: Vec<OsString> = std::env::args_os().skip(1).collect();

    if args.is_empty() {
        emit_usage_error(b"Hey, mkdir needs an operand!");
        return ExitCode::from(1);
    }

    let mut parents = false;
    let mut operands: Vec<OsString> = Vec::new();
    let mut after_ddash = false;

    for arg in &args {
        let bytes = arg.as_bytes();
        if after_ddash {
            operands.push(arg.clone());
            continue;
        }
        if bytes == b"--" {
            after_ddash = true;
            continue;
        }
        if bytes.len() >= 2 && bytes[0] == b'-' && bytes[1] != b'-' {
            if bytes == b"-p" {
                parents = true;
                continue;
            }
            let mut stderr = std::io::stderr().lock();
            let _ = stderr.write_all(b"mkdir: invalid option -- '");
            let _ = stderr.write_all(&bytes[1..2]);
            let _ = stderr.write_all(
                b"'\nTry 'mkdir --help' for more information.\n",
            );
            return ExitCode::from(1);
        }
        if bytes.len() >= 3 && bytes[0] == b'-' && bytes[1] == b'-' {
            if bytes == b"--parents" {
                parents = true;
                continue;
            }
            let mut stderr = std::io::stderr().lock();
            let _ = stderr.write_all(b"mkdir: unrecognized option '");
            let _ = stderr.write_all(bytes);
            let _ = stderr.write_all(
                b"'\nTry 'mkdir --help' for more information.\n",
            );
            return ExitCode::from(1);
        }
        operands.push(arg.clone());
    }

    if operands.is_empty() {
        emit_usage_error(b"Hey, mkdir needs an operand!");
        return ExitCode::from(1);
    }

    let mut any_failed = false;
    for operand in &operands {
        let result = if parents {
            create_parents(operand)
        } else {
            std::fs::create_dir(operand)
        };
        if let Err(e) = result {
            emit_create_error(operand, &e);
            any_failed = true;
        }
    }

    if any_failed {
        ExitCode::from(1)
    } else {
        ExitCode::SUCCESS
    }
}

fn create_parents(operand: &OsString) -> Result<(), std::io::Error> {
    let path = Path::new(operand);

    if is_dir_or_symlink_to_dir(path) {
        return Ok(());
    }

    let mut ancestors: Vec<&Path> = Vec::new();
    let mut p = path;
    while let Some(parent) = p.parent() {
        if parent.as_os_str().is_empty() {
            break;
        }
        ancestors.push(parent);
        p = parent;
    }
    ancestors.reverse();

    for ancestor in &ancestors {
        if is_dir_or_symlink_to_dir(ancestor) {
            continue;
        }
        if ancestor.symlink_metadata().is_ok() {
            return Err(std::io::Error::new(
                std::io::ErrorKind::AlreadyExists,
                "File exists",
            ));
        }
        std::fs::create_dir(ancestor)?;
    }

    std::fs::create_dir(path)?;
    Ok(())
}

fn is_dir_or_symlink_to_dir(p: &Path) -> bool {
    std::fs::metadata(p).map(|m| m.is_dir()).unwrap_or(false)
}

fn emit_create_error(operand: &OsString, e: &std::io::Error) {
    let errno = e.raw_os_error().unwrap_or(17);
    let msg = errno_to_message(errno);
    let mut stderr = std::io::stderr().lock();
    let _ = stderr.write_all(b"mkdir: cannot create directory '");
    let _ = stderr.write_all(operand.as_bytes());
    let _ = stderr.write_all(b"': ");
    let _ = stderr.write_all(msg.as_bytes());
    let _ = stderr.write_all(b"\n");
}

fn emit_usage_error(prefix: &[u8]) {
    let mut stderr = std::io::stderr().lock();
    let _ = stderr.write_all(prefix);
    let _ = stderr.write_all(b"\nTry 'mkdir --help' for more information.\n");
}

fn errno_to_message(errno: i32) -> &'static str {
    match errno {
        1 => "Operation not permitted",
        2 => "No such file or directory",
        5 => "Input/output error",
        12 => "Cannot allocate memory",
        13 => "Permission denied",
        16 => "Resource busy",
        17 => "File exists",
        20 => "Not a directory",
        21 => "Is a directory",
        22 => "Invalid argument",
        23 => "File table overflow",
        24 => "Too many open files",
        27 => "File too large",
        28 => "No space left on device",
        30 => "Read-only file system",
        36 => "File name too long",
        38 => "Function not implemented",
        39 => "Directory not empty",
        40 => "Too many levels of symbolic links",
        _ => "Unknown error",
    }
}
