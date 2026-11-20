use std::env;
use std::ffi::OsString;
use std::fs;
use std::io::Write;
use std::process;
use std::os::unix::ffi::OsStringExt;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::PermissionsExt;

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

fn normalize_path(path: &OsString) -> (bool, Vec<OsString>) {
    let bytes = path.as_encoded_bytes();
    let is_absolute = bytes.starts_with(b"/");
    let mut components: Vec<OsString> = Vec::new();
    let mut current: Vec<u8> = Vec::new();

    for &b in bytes {
        if b == b'/' {
            if !current.is_empty() {
                if current != b"." {
                    if current == b".." {
                        components.pop();
                    } else {
                        components.push(OsString::from_vec(current.clone()));
                    }
                }
            }
            current.clear();
        } else {
            current.push(b);
        }
    }
    if !current.is_empty() && current != b"." {
        if current == b".." {
            components.pop();
        } else {
            components.push(OsString::from_vec(current));
        }
    }
    (is_absolute, components)
}

fn build_path(is_absolute: bool, components: &[OsString], up_to: usize) -> OsString {
    if is_absolute {
        if up_to == 0 {
            return OsString::from("/");
        }
        let mut result = OsString::from("/");
        for (i, comp) in components.iter().take(up_to).enumerate() {
            if i > 0 {
                result.push("/");
            }
            result.push(comp);
        }
        result
    } else {
        let mut result = OsString::new();
        for (i, comp) in components.iter().take(up_to).enumerate() {
            if i > 0 {
                result.push("/");
            }
            result.push(comp);
        }
        result
    }
}

fn create_with_parents(op: &OsString) -> bool {
    let (is_absolute, components) = normalize_path(op);

    if components.is_empty() {
        return true;
    }

    for i in 0..components.len() {
        let next = build_path(is_absolute, &components, i + 1);
        let is_final = i + 1 == components.len();

        match fs::metadata(&next) {
            Ok(meta) => {
                if !meta.is_dir() {
                    let mut err = std::io::stderr().lock();
                    let _ = write!(err, "mkdir: cannot create directory '");
                    let _ = err.write_all(op.as_encoded_bytes());
                    let _ = writeln!(err, "': Not a directory");
                    return false;
                }
            }
            Err(ref e) if e.kind() == std::io::ErrorKind::NotFound => {
                if let Err(e) = fs::create_dir(&next) {
                    let errno = e.raw_os_error().unwrap_or(-1);
                    let msg = errno_to_str(errno);
                    let mut err = std::io::stderr().lock();
                    let _ = write!(err, "mkdir: cannot create directory '");
                    let _ = err.write_all(op.as_encoded_bytes());
                    let _ = writeln!(err, "': {}", msg);
                    return false;
                }
                if !is_final {
                    if let Ok(meta) = fs::metadata(&next) {
                        let mode = meta.mode() | 0o300;
                        let _ = fs::set_permissions(&next, fs::Permissions::from_mode(mode));
                    }
                }
            }
            Err(e) => {
                let errno = e.raw_os_error().unwrap_or(-1);
                let msg = errno_to_str(errno);
                let mut err = std::io::stderr().lock();
                let _ = write!(err, "mkdir: cannot create directory '");
                let _ = err.write_all(op.as_encoded_bytes());
                let _ = writeln!(err, "': {}", msg);
                return false;
            }
        }
    }
    true
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
    let mut parents = false;

    for arg in &args {
        let b = arg.as_encoded_bytes();
        if after_ddash {
            operands.push(arg.clone());
        } else if b == b"--" {
            after_ddash = true;
        } else if b == b"-p" {
            parents = true;
        } else if b == b"--parents" {
            parents = true;
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
        if parents {
            if !create_with_parents(op) {
                all_ok = false;
            }
        } else {
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
    }

    process::exit(if all_ok { 0 } else { 1 });
}
