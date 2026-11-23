use std::io::Write;
use std::os::unix::ffi::OsStrExt;
use std::os::unix::fs::DirBuilderExt;
use std::os::unix::fs::PermissionsExt;

fn main() {
    let args: Vec<std::ffi::OsString> = std::env::args_os().skip(1).collect();

    let mut seen_dd = false;
    let mut operands: Vec<std::ffi::OsString> = Vec::new();
    let mut parents = false;
    let mut mode_str: Option<String> = None;

    // Parse arguments
    let mut i = 0;
    while i < args.len() {
        let arg = &args[i];
        let bytes = arg.as_bytes();
        
        if seen_dd {
            operands.push(arg.clone());
            i += 1;
            continue;
        }
        
        if bytes == b"--" {
            seen_dd = true;
        } else if bytes == b"-" {
            operands.push(arg.clone());
        } else if bytes == b"-p" {
            parents = true;
        } else if bytes == b"--parents" {
            parents = true;
        } else if bytes == b"-m" {
            if i + 1 >= args.len() {
                let msg = b"mkdir: option requires an argument -- 'm'\n";
                let stderr = std::io::stderr();
                let mut lock = stderr.lock();
                let _ = lock.write_all(msg);
                std::process::exit(1);
            }
            i += 1;
            let next_arg = &args[i];
            let mode_val = next_arg.to_string_lossy();
            if mode_val.is_empty() {
                let msg = format!("mkdir: invalid mode ''\n");
                let stderr = std::io::stderr();
                let mut lock = stderr.lock();
                let _ = lock.write_all(msg.as_bytes());
                std::process::exit(1);
            }
            mode_str = Some(mode_val.into_owned());
        } else if bytes.starts_with(b"-m") && bytes.len() > 2 {
            let mode_part = &bytes[2..];
            if mode_part.is_empty() {
                let msg = b"mkdir: invalid mode ''\n";
                let stderr = std::io::stderr();
                let mut lock = stderr.lock();
                let _ = lock.write_all(msg);
                std::process::exit(1);
            }
            let mode_val = String::from_utf8_lossy(mode_part);
            if mode_val.is_empty() {
                let msg = b"mkdir: invalid mode ''\n";
                let stderr = std::io::stderr();
                let mut lock = stderr.lock();
                let _ = lock.write_all(msg);
                std::process::exit(1);
            }
            mode_str = Some(mode_val.into_owned());
        } else if bytes == b"--mode" {
            if i + 1 >= args.len() {
                let msg = b"mkdir: option '--mode' requires an argument\n";
                let stderr = std::io::stderr();
                let mut lock = stderr.lock();
                let _ = lock.write_all(msg);
                std::process::exit(1);
            }
            i += 1;
            let next_arg = &args[i];
            let mode_val = next_arg.to_string_lossy();
            if mode_val.is_empty() {
                let msg = b"mkdir: invalid mode ''\n";
                let stderr = std::io::stderr();
                let mut lock = stderr.lock();
                let _ = lock.write_all(msg);
                std::process::exit(1);
            }
            mode_str = Some(mode_val.into_owned());
        } else if bytes.starts_with(b"--mode=") {
            let mode_part = &bytes[7..];
            if mode_part.is_empty() {
                let msg = b"mkdir: invalid mode ''\n";
                let stderr = std::io::stderr();
                let mut lock = stderr.lock();
                let _ = lock.write_all(msg);
                std::process::exit(1);
            }
            let mode_val = String::from_utf8_lossy(mode_part);
            if mode_val.is_empty() {
                let msg = b"mkdir: invalid mode ''\n";
                let stderr = std::io::stderr();
                let mut lock = stderr.lock();
                let _ = lock.write_all(msg);
                std::process::exit(1);
            }
            mode_str = Some(mode_val.into_owned());
        } else if bytes.first() == Some(&b'-') {
            let mut out: Vec<u8> = Vec::new();
            if bytes.len() > 1 && bytes[1] == b'-' {
                out.extend_from_slice(b"mkdir: unrecognized option '");
                out.extend_from_slice(bytes);
                out.extend_from_slice(b"'\nTry 'mkdir --help' for more information.\n");
            } else {
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
        i += 1;
    }

    if operands.is_empty() {
        let msg = b"mkdir: missing operand\nTry 'mkdir --help' for more information.\n";
        let stderr = std::io::stderr();
        let mut lock = stderr.lock();
        let _ = lock.write_all(msg);
        std::process::exit(1);
    }

    // Parse mode if specified
    let mode_val: Option<u32> = if let Some(ref ms) = mode_str {
        match parse_mode(ms) {
            Ok((m, _)) => Some(m),
            Err(_) => {
                let msg = format!("mkdir: invalid mode '{}'\n", ms);
                let stderr = std::io::stderr();
                let mut lock = stderr.lock();
                let _ = lock.write_all(msg.as_bytes());
                std::process::exit(1);
            }
        }
    } else {
        None
    };

    let create_mode = mode_val.unwrap_or(0o777);
    let should_chmod = mode_val.is_some();

    let mut any_failed = false;
    for operand in &operands {
        let path = std::path::Path::new(operand);
        let (result, newly_created): (Result<(), std::io::Error>, bool) = if parents {
            create_parents(path, create_mode)
        } else {
            match std::fs::DirBuilder::new().mode(create_mode).create(path) {
                Ok(()) => (Ok(()), true),
                Err(e) => (Err(e), false),
            }
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
        } else if newly_created && should_chmod {
            if let Some(m) = mode_val {
                if let Err(e) = std::fs::set_permissions(path, std::fs::Permissions::from_mode(m)) {
                    any_failed = true;
                    let err_msg = os_error_message(&e);
                    let mut out: Vec<u8> = Vec::new();
                    out.extend_from_slice(b"mkdir: cannot set permissions on '");
                    out.extend_from_slice(operand.as_bytes());
                    out.extend_from_slice(b"': ");
                    out.extend_from_slice(err_msg.as_bytes());
                    out.extend_from_slice(b"\n");
                    let stderr = std::io::stderr();
                    let mut lock = stderr.lock();
                    let _ = lock.write_all(&out);
                }
            }
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

/// Get the current umask by creating a temp directory and checking its mode.
fn get_umask() -> u32 {
    let name = format!("_umask_probe_{}", std::process::id());
    if let Ok(()) = std::fs::create_dir(&name) {
        if let Ok(meta) = std::fs::metadata(&name) {
            let _ = std::fs::remove_dir(&name);
            let mode = meta.permissions().mode();
            return 0o777 & !mode;
        }
        let _ = std::fs::remove_dir(&name);
    }
    0o022
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

/// Parse a mode string into a mode value and a flag indicating if ordinary permissions are explicitly assigned.
fn parse_mode(s: &str) -> Result<(u32, bool), ()> {
    if !s.is_empty() && s.bytes().all(|b| b.is_ascii_digit() && b <= b'7') {
        return parse_numeric_mode(s);
    }
    let umask = get_umask();
    parse_symbolic_mode(s, umask)
}

/// Parse a numeric mode string.
fn parse_numeric_mode(s: &str) -> Result<(u32, bool), ()> {
    let val = u32::from_str_radix(s, 8).map_err(|_| ())?;
    if val > 0o7777 {
        return Err(());
    }
    Ok((val, true))
}

/// Parse a symbolic mode string.
fn parse_symbolic_mode(s: &str, umask: u32) -> Result<(u32, bool), ()> {
    let mut mode: u32 = 0o777;
    let mut explicitly_assigns = false;
    let mut any_ordinary = false;
    let mut any_s = false;
    let mut any_t = false;

    for clause in s.split(',') {
        if clause.is_empty() {
            return Err(());
        }

        let bytes = clause.as_bytes();
        let mut pos = 0;
        let mut who_u = false;
        let mut who_g = false;
        let mut who_o = false;

        while pos < bytes.len() {
            match bytes[pos] {
                b'u' => { who_u = true; pos += 1; }
                b'g' => { who_g = true; pos += 1; }
                b'o' => { who_o = true; pos += 1; }
                b'a' => { who_u = true; who_g = true; who_o = true; pos += 1; }
                _ => break,
            }
        }

        if pos >= bytes.len() {
            return Err(());
        }

        let op = bytes[pos];
        pos += 1;
        if !matches!(op, b'+' | b'-' | b'=') {
            return Err(());
        }

        let perm_str = &clause[pos..];
        for c in perm_str.bytes() {
            if !matches!(c, b'r' | b'w' | b'x' | b'X' | b's' | b't' | b'u' | b'g' | b'o') {
                return Err(());
            }
        }

        if (op == b'+' || op == b'-') && perm_str.is_empty() {
            return Err(());
        }

        let perm_r = perm_str.contains('r');
        let perm_w = perm_str.contains('w');
        let perm_x = perm_str.contains('x') || perm_str.contains('X');
        let perm_s = perm_str.contains('s');
        let perm_t = perm_str.contains('t');
        let copy_u = perm_str.contains('u');
        let copy_g = perm_str.contains('g');
        let copy_o = perm_str.contains('o');

        if perm_r || perm_w || perm_x || perm_str.contains('X') || copy_u || copy_g || copy_o {
            any_ordinary = true;
        }
        if perm_s { any_s = true; }
        if perm_t { any_t = true; }

        let src_u_rwx = (mode & 0o700) >> 6;
        let src_g_rwx = (mode & 0o070) >> 3;
        let src_o_rwx = mode & 0o007;

        let eff_r = perm_r || (copy_u && (src_u_rwx & 0o4) != 0) || (copy_g && (src_g_rwx & 0o4) != 0) || (copy_o && (src_o_rwx & 0o4) != 0);
        let eff_w = perm_w || (copy_u && (src_u_rwx & 0o2) != 0) || (copy_g && (src_g_rwx & 0o2) != 0) || (copy_o && (src_o_rwx & 0o2) != 0);
        let eff_x = perm_x || (copy_u && (src_u_rwx & 0o1) != 0) || (copy_g && (src_g_rwx & 0o1) != 0) || (copy_o && (src_o_rwx & 0o1) != 0);

        let u_bits = (if eff_r { 0o400 } else { 0 }) | (if eff_w { 0o200 } else { 0 }) | (if eff_x { 0o100 } else { 0 });
        let g_bits = (if eff_r { 0o040 } else { 0 }) | (if eff_w { 0o020 } else { 0 }) | (if eff_x { 0o010 } else { 0 });
        let o_bits = (if eff_r { 0o004 } else { 0 }) | (if eff_w { 0o002 } else { 0 }) | (if eff_x { 0o001 } else { 0 });

        let all_who_omitted = !who_u && !who_g && !who_o;
        let mask = 0o777 & !umask;

        if all_who_omitted {
            let applied = (u_bits | g_bits | o_bits) & mask;
            match op {
                b'+' => { mode |= applied; }
                b'-' => { mode &= !applied; }
                b'=' => { mode = (mode & !0o777) | applied; }
                _ => {}
            }
            // Special bits with omitted who
            if op == b'=' {
                if perm_s { mode |= 0o4000 | 0o2000; }
                if perm_t { mode |= 0o1000; } else { mode &= !0o1000; }
            } else if op == b'+' {
                if perm_s { mode |= 0o4000 | 0o2000; }
                if perm_t { mode |= 0o1000; }
            } else if op == b'-' {
                if perm_s { mode &= !(0o4000 | 0o2000); }
                if perm_t { mode &= !0o1000; }
            }
            // Track explicit ordinary assignment
            if op == b'=' {
                let has_ordinary = perm_str.is_empty() || perm_r || perm_w || perm_x || perm_str.contains('X') || copy_u || copy_g || copy_o;
                if has_ordinary {
                    explicitly_assigns = true;
                }
            }
        } else {
            // Explicit who
            match op {
                b'+' => {
                    if who_u { mode |= u_bits; }
                    if who_g { mode |= g_bits; }
                    if who_o { mode |= o_bits; }
                }
                b'-' => {
                    if who_u { mode &= !u_bits; }
                    if who_g { mode &= !g_bits; }
                    if who_o { mode &= !o_bits; }
                }
                b'=' => {
                    if who_u { mode = (mode & !0o700) | u_bits; }
                    if who_g { mode = (mode & !0o070) | g_bits; }
                    if who_o { mode = (mode & !0o007) | o_bits; }
                }
                _ => {}
            }
            // Special bits with explicit who
            if op == b'=' {
                if who_u && perm_s { mode |= 0o4000; }
                if who_g && perm_s { mode |= 0o2000; }
                if (who_o) && perm_t { mode |= 0o1000; }
                if (who_o) && !perm_t { mode &= !0o1000; }
            } else if op == b'+' {
                if who_u && perm_s { mode |= 0o4000; }
                if who_g && perm_s { mode |= 0o2000; }
                if who_o && perm_t { mode |= 0o1000; }
            } else if op == b'-' {
                if who_u && perm_s { mode &= !0o4000; }
                if who_g && perm_s { mode &= !0o2000; }
                if who_o && perm_t { mode &= !0o1000; }
            }
            if op == b'=' {
                let has_ordinary = perm_str.is_empty() || perm_r || perm_w || perm_x || perm_str.contains('X') || copy_u || copy_g || copy_o;
                if has_ordinary {
                    explicitly_assigns = true;
                }
            }
        }
    }

    // GNU sticky-only rule: +t / a+t yield ordinary 0755, not 0777.
    if any_t && !any_ordinary && !any_s {
        mode = (mode & 0o7000) | 0o755;
    }

    Ok((mode, explicitly_assigns))
}

/// Create all missing intermediate directories plus the final directory.
/// Existing directories (or symlinks resolving to directories) are accepted.
/// Existing non-directories are an error (ENOTDIR).
fn create_parents(path: &std::path::Path, final_mode: u32) -> (Result<(), std::io::Error>, bool) {
    if path.as_os_str().is_empty() {
        return (std::fs::create_dir(path).map(|()| ()), true);
    }

    let normalized = normalize_path(path);

    if normalized == std::path::Path::new("/") || normalized.as_os_str().is_empty() {
        return (Ok(()), false);
    }

    let components: Vec<std::path::Component> = normalized.components().collect();
    let n = components.len();
    let mut prefix = std::path::PathBuf::new();
    let mut newly_created_final = false;

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
                            match std::fs::metadata(&prefix) {
                                Ok(m2) if m2.is_dir() => continue,
                                _ => {
                                    return (Err(std::io::Error::from_raw_os_error(20)), false);
                                }
                            }
                        }
                        if is_final {
                            return (Err(std::io::Error::from_raw_os_error(17)), false);
                        }
                        return (Err(std::io::Error::from_raw_os_error(20)), false);
                    }
                    Err(_) => {
                        let builder_mode = if is_final { final_mode } else { 0o777 };
                        match std::fs::DirBuilder::new().mode(builder_mode).create(&prefix) {
                            Ok(()) => {}
                            Err(e) => return (Err(e), false),
                        }
                        if !is_final {
                            match std::fs::metadata(&prefix) {
                                Ok(m) => {
                                    let cur = m.permissions().mode();
                                    let want = cur | 0o300;
                                    if cur != want {
                                        if let Err(e) = std::fs::set_permissions(
                                            &prefix,
                                            std::fs::Permissions::from_mode(want),
                                        ) {
                                            return (Err(e), false);
                                        }
                                    }
                                }
                                Err(e) => return (Err(e), false),
                            }
                        } else {
                            newly_created_final = true;
                        }
                    }
                }
            }
            _ => {}
        }
    }

    (Ok(()), newly_created_final)
}
