use std::ffi::OsString;
use std::os::unix::ffi::OsStrExt;
use std::os::unix::fs::PermissionsExt;

fn errno_string(e: &std::io::Error) -> String {
    let s = e.to_string();
    if let Some(idx) = s.rfind(" (os error ") {
        s[..idx].to_string()
    } else {
        s
    }
}

fn ensure_owner_wx(path: &std::ffi::OsStr) {
    if let Ok(md) = std::fs::metadata(path) {
        let mode = md.permissions().mode() & 0o7777;
        if mode & 0o300 != 0o300 {
            let mut perms = md.permissions();
            perms.set_mode(mode | 0o300);
            let _ = std::fs::set_permissions(path, perms);
        }
    }
}

fn create_dir_with_parents(path: &std::ffi::OsStr) -> std::io::Result<()> {
    let bytes = path.as_bytes();
    let is_absolute = bytes.first() == Some(&b'/');

    let components: Vec<&[u8]> = bytes
        .split(|&b| b == b'/')
        .filter(|c| !c.is_empty() && c != b".")
        .collect();

    if components.is_empty() {
        return Ok(());
    }

    let mut current = std::ffi::OsString::new();

    for (i, comp) in components.iter().enumerate() {
        let is_last = i == components.len() - 1;
        let comp_os = std::ffi::OsStr::from_bytes(comp);

        if i == 0 {
            if is_absolute {
                current.push("/");
            }
            current.push(comp_os);
        } else {
            current.push("/");
            current.push(comp_os);
        }

        match std::fs::create_dir(&current) {
            Ok(()) => {
                if !is_last {
                    ensure_owner_wx(&current);
                }
            }
            Err(e) => {
                if e.kind() == std::io::ErrorKind::AlreadyExists {
                    if is_last {
                        match std::fs::metadata(&current) {
                            Ok(md) if md.is_dir() => {}
                            _ => return Err(e),
                        }
                    }
                    // Intermediate: accept EEXIST (GNU behavior)
                } else {
                    return Err(e);
                }
            }
        }
    }

    Ok(())
}

fn main() {
    let args: Vec<OsString> = std::env::args_os().skip(1).collect();

    let mut operands: Vec<OsString> = Vec::new();
    let mut option_terminated = false;
    let mut parents = false;

    for arg in &args {
        if !option_terminated {
            let bytes = arg.as_bytes();
            if bytes.len() > 1 && bytes[0] == b'-' {
                if bytes == b"--" {
                    option_terminated = true;
                    continue;
                }
                if bytes == b"-p" {
                    parents = true;
                    continue;
                }
                if bytes == b"--parents" {
                    parents = true;
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
        let result = if parents {
            create_dir_with_parents(op)
        } else {
            std::fs::create_dir(op)
        };
        if let Err(e) = result {
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
