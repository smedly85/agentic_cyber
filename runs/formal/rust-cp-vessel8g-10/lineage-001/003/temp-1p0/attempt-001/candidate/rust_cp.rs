use std::env;
use std::ffi::{OsStr, OsString};
use std::fs;
use std::fs::DirBuilder;
use std::io::{self, Read, Write};
use std::os::unix::ffi::OsStrExt;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::fs::PermissionsExt;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::DirBuilderExt;
use std::os::unix::fs::symlink;
use std::path::Path;

enum CopyOutcome {
    Success,
    Declined,
    Error(String),
}

fn main() {
    let args: Vec<OsString> = env::args_os().collect();
    let user_args: &[OsString] = &args[1..];

    let (operands, force, interactive, recursive) = match parse_operands(user_args) {
        Ok(v) => v,
        Err(msg) => {
            eprintln!("{}", msg);
            std::process::exit(1);
        }
    };

    if operands.len() < 2 {
        eprintln!("error: requires at least SOURCE and DEST");
        std::process::exit(1);
    }

    let pairs: Vec<(OsString, OsString)> = if operands.len() == 2 {
        let src = &operands[0];
        let dst = &operands[1];
        if recursive {
            if Path::new(dst).is_dir() {
                vec![(src.clone(), Path::new(dst).join(basename(src)).into_os_string())]
            } else {
                vec![(src.clone(), dst.clone())]
            }
        } else {
            if Path::new(dst).is_dir() {
                vec![(src.clone(), Path::new(dst).join(basename(src)).into_os_string())]
            } else {
                vec![(src.clone(), dst.clone())]
            }
        }
    } else {
        let dir = &operands[operands.len() - 1];
        if !Path::new(dir).is_dir() {
            eprintln!("error: {} is not a directory", os_display(dir));
            std::process::exit(1);
        }
        operands[..operands.len() - 1]
            .iter()
            .map(|src| (src.clone(), Path::new(dir).join(basename(src)).into_os_string()))
            .collect()
    };

    let mut had_error = false;
    for (src, dst) in &pairs {
        let src_path = Path::new(src);
        let dst_path = Path::new(dst);
        let outcome = if recursive {
            match fs::symlink_metadata(src_path) {
                Ok(m) if m.file_type().is_symlink() => {
                    // Operand symlink in recursive mode: recreate, do not traverse.
                    let target = fs::read_link(src_path)
                        .map_err(|e| e.to_string())
                        .and_then(|target| {
                            if let Ok(existing) = dst_path.symlink_metadata() {
                                if existing.is_dir() {
                                    return Err(format!("{}: is a directory", dst_path.display()));
                                }
                                fs::remove_file(dst_path).map_err(|e| e.to_string())?;
                            }
                            symlink(&target, dst_path).map_err(|e| e.to_string())?;
                            Ok(())
                        });
                    match target {
                        Ok(()) => CopyOutcome::Success,
                        Err(msg) => CopyOutcome::Error(msg),
                    }
                }
                Ok(m) if m.is_dir() => {
                    copy_dir_recursive(src_path, dst_path, force, interactive)
                }
                _ => {
                    copy_path(src_path, dst_path, force, interactive)
                }
            }
        } else {
            copy_path(src_path, dst_path, force, interactive)
        };
        match outcome {
            CopyOutcome::Success => {}
            CopyOutcome::Declined => {
                had_error = true;
            }
            CopyOutcome::Error(msg) => {
                eprintln!("error: {}: {}", os_display(src), msg);
                had_error = true;
            }
        }
    }

    if had_error {
        std::process::exit(1);
    }
}

fn parse_operands(args: &[OsString]) -> Result<(Vec<OsString>, bool, bool, bool), String> {
    let mut operands = Vec::new();
    let mut force = false;
    let mut interactive = false;
    let mut recursive = false;
    let mut after_separator = false;

    for arg in args {
        if !after_separator && arg.as_os_str() == OsStr::new("--") {
            after_separator = true;
            continue;
        }
        if !after_separator {
            let bytes = arg.as_bytes();
            if bytes.len() > 1 && bytes[0] == b'-' {
                if arg.as_os_str() == OsStr::new("-f") || arg.as_os_str() == OsStr::new("--force") {
                    force = true;
                    continue;
                }
                if arg.as_os_str() == OsStr::new("-i") || arg.as_os_str() == OsStr::new("--interactive") {
                    interactive = true;
                    continue;
                }
                if arg.as_os_str() == OsStr::new("-r") || arg.as_os_str() == OsStr::new("--recursive") {
                    recursive = true;
                    continue;
                }
                return Err(format!(
                    "error: unknown option '{}'",
                    os_display(arg.as_os_str())
                ));
            }
        }
        operands.push(arg.clone());
    }

    Ok((operands, force, interactive, recursive))
}

fn basename(path: &OsStr) -> OsString {
    Path::new(path)
        .file_name()
        .map(|f| f.to_os_string())
        .unwrap_or_else(|| path.to_os_string())
}

fn os_display(s: &OsStr) -> String {
    s.to_string_lossy().into_owned()
}

fn prompt_yes() -> bool {
    let mut stdin = std::io::stdin().lock();
    let mut line = Vec::new();
    let mut byte = [0u8; 1];
    loop {
        match stdin.read(&mut byte) {
            Ok(0) => break,
            Ok(_) => {
                if byte[0] == b'\n' {
                    break;
                }
                line.push(byte[0]);
            }
            Err(_) => break,
        }
    }
    line.first() == Some(&b'y') || line.first() == Some(&b'Y')
}

fn copy_path(src: &Path, dst: &Path, force: bool, interactive: bool) -> CopyOutcome {
    // Reject self-copy (same inode) before any destructive change.
    if let (Ok(s_meta), Ok(d_meta)) = (fs::metadata(src), fs::metadata(dst)) {
        if s_meta.dev() == d_meta.dev() && s_meta.ino() == d_meta.ino() {
            return CopyOutcome::Error(format!(
                "'{}' and '{}' are the same file",
                src.display(),
                dst.display()
            ));
        }
    }

    // Reject directory sources (non-recursive mode).
    if let Ok(s_meta) = fs::metadata(src) {
        if s_meta.is_dir() {
            return CopyOutcome::Error(format!("'{}' is a directory", src.display()));
        }
    }

    let mut src_file = match fs::File::open(src) {
        Ok(f) => f,
        Err(e) => return CopyOutcome::Error(e.to_string()),
    };
    let mode = match src_file.metadata() {
        Ok(m) => m.permissions().mode() & 0o777,
        Err(e) => return CopyOutcome::Error(e.to_string()),
    };

    // Inspect destination via lstat
    if let Ok(dst_meta) = fs::symlink_metadata(dst) {
        if dst_meta.is_dir() {
            return CopyOutcome::Error(format!("{}: is a directory", dst.display()));
        }

        // Destination exists and is not a directory; prompt if interactive
        if interactive {
            eprint!("cp: overwrite '{}'? ", dst.display());
            let _ = std::io::stderr().flush();
            if !prompt_yes() {
                return CopyOutcome::Declined;
            }
        }

        if dst_meta.file_type().is_symlink() {
            match fs::metadata(dst) {
                Ok(target) => {
                    if !target.is_file() {
                        return CopyOutcome::Error(format!("{}: not a regular file", dst.display()));
                    }
                    let mut dst_file = match fs::OpenOptions::new()
                        .write(true)
                        .truncate(true)
                        .open(dst)
                    {
                        Ok(f) => f,
                        Err(e) => return CopyOutcome::Error(e.to_string()),
                    };
                    if let Err(e) = io::copy(&mut src_file, &mut dst_file) {
                        return CopyOutcome::Error(e.to_string());
                    }
                    return CopyOutcome::Success;
                }
                Err(_) => {
                    // Dangling symlink
                    if !force {
                        return CopyOutcome::Error(format!("{}: dangling symlink", dst.display()));
                    }
                    if let Err(e) = fs::remove_file(dst) {
                        return CopyOutcome::Error(e.to_string());
                    }
                }
            }
        }
    }

    // Open destination for writing (truncates existing files, creates new ones)
    let mut dst_file = match fs::OpenOptions::new()
        .write(true)
        .create(true)
        .truncate(true)
        .mode(mode)
        .open(dst)
    {
        Ok(f) => f,
        Err(e) if force => {
            if let Ok(meta) = fs::symlink_metadata(dst) {
                if meta.is_dir() {
                    return CopyOutcome::Error(e.to_string());
                }
                if let Err(re) = fs::remove_file(dst) {
                    return CopyOutcome::Error(re.to_string());
                }
            }
            match fs::OpenOptions::new()
                .write(true)
                .create(true)
                .truncate(true)
                .mode(mode)
                .open(dst)
            {
                Ok(f) => f,
                Err(e) => return CopyOutcome::Error(e.to_string()),
            }
        }
        Err(e) => return CopyOutcome::Error(e.to_string()),
    };

    if let Err(e) = io::copy(&mut src_file, &mut dst_file) {
        return CopyOutcome::Error(e.to_string());
    }
    CopyOutcome::Success
}

fn copy_dir_recursive(src: &Path, dst: &Path, force: bool, interactive: bool) -> CopyOutcome {
    // Reject copying a directory into itself or a descendant.
    if let Ok(src_canon) = fs::canonicalize(src) {
        match fs::canonicalize(dst) {
            Ok(dst_canon) => {
                if src_canon == dst_canon
                    || src_canon.starts_with(&dst_canon)
                    || dst_canon.starts_with(&src_canon)
                {
                    return CopyOutcome::Error(format!(
                        "cannot copy a directory into itself: {}",
                        dst.display()
                    ));
                }
            }
            Err(_) => {
                // dst does not exist; reject if it would be created inside src.
                let dst_abs = if dst.is_absolute() {
                    dst.to_path_buf()
                } else {
                    std::env::current_dir()
                        .map(|cwd| cwd.join(dst))
                        .unwrap_or_else(|_| dst.to_path_buf())
                };
                if dst_abs.starts_with(&src_canon) {
                    return CopyOutcome::Error(format!(
                        "cannot copy a directory into itself: {}",
                        dst.display()
                    ));
                }
            }
        }
    }

    // Ensure the destination directory exists.
    if !dst.symlink_metadata().is_ok() {
        // Missing: create as the tree root.
        let src_meta = match fs::metadata(src) {
            Ok(m) => m,
            Err(e) => return CopyOutcome::Error(e.to_string()),
        };
        let mode = src_meta.permissions().mode() & 0o777;
        if let Err(e) = DirBuilder::new().mode(mode).create(dst) {
            return CopyOutcome::Error(e.to_string());
        }
    } else {
        // Exists: must be a directory (or symlink to one).
        let dst_meta = match fs::metadata(dst) {
            Ok(m) => m,
            Err(e) => return CopyOutcome::Error(e.to_string()),
        };
        if !dst_meta.is_dir() {
            return CopyOutcome::Error(format!("{}: not a directory", dst.display()));
        }
    }

    // Iterate over source entries.
    let entries = match fs::read_dir(src) {
        Ok(e) => e,
        Err(e) => return CopyOutcome::Error(e.to_string()),
    };

    let mut had_error = false;
    let mut first_error = String::new();
    let mut had_declined = false;

    for entry in entries {
        let entry = match entry {
            Ok(e) => e,
            Err(e) => {
                had_error = true;
                if first_error.is_empty() {
                    first_error = e.to_string();
                }
                continue;
            }
        };
        let entry_path = entry.path();
        let entry_name = entry.file_name();
        let dest_entry = dst.join(&entry_name);

        let file_type = match entry.file_type() {
            Ok(ft) => ft,
            Err(e) => {
                had_error = true;
                if first_error.is_empty() {
                    first_error = e.to_string();
                }
                continue;
            }
        };

        if file_type.is_symlink() {
            let target = match fs::read_link(&entry_path) {
                Ok(t) => t,
                Err(e) => {
                    had_error = true;
                    if first_error.is_empty() {
                        first_error = e.to_string();
                    }
                    continue;
                }
            };
            if let Ok(existing) = dest_entry.symlink_metadata() {
                if existing.is_dir() {
                    had_error = true;
                    if first_error.is_empty() {
                        first_error = format!("{}: is a directory", dest_entry.display());
                    }
                    continue;
                }
                if let Err(e) = fs::remove_file(&dest_entry) {
                    had_error = true;
                    if first_error.is_empty() {
                        first_error = e.to_string();
                    }
                    continue;
                }
            }
            if let Err(e) = symlink(&target, &dest_entry) {
                had_error = true;
                if first_error.is_empty() {
                    first_error = e.to_string();
                }
                continue;
            }
        } else if file_type.is_dir() {
            match copy_dir_recursive(&entry_path, &dest_entry, force, interactive) {
                CopyOutcome::Success => {}
                CopyOutcome::Declined => had_declined = true,
                CopyOutcome::Error(msg) => {
                    had_error = true;
                    if first_error.is_empty() {
                        first_error = msg;
                    }
                }
            }
        } else if file_type.is_file() {
            match copy_path(&entry_path, &dest_entry, force, interactive) {
                CopyOutcome::Success => {}
                CopyOutcome::Declined => had_declined = true,
                CopyOutcome::Error(msg) => {
                    had_error = true;
                    if first_error.is_empty() {
                        first_error = msg;
                    }
                }
            }
        }
    }

    if had_error {
        CopyOutcome::Error(first_error)
    } else if had_declined {
        CopyOutcome::Declined
    } else {
        CopyOutcome::Success
    }
}
