use std::env;
use std::ffi::{OsStr, OsString};
use std::fs;
use std::io;
use std::os::unix::ffi::OsStrExt;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;

fn main() {
    let args: Vec<OsString> = env::args_os().collect();
    let user_args: &[OsString] = &args[1..];

    let (operands, force) = match parse_operands(user_args) {
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
        if Path::new(dst).is_dir() {
            vec![(src.clone(), Path::new(dst).join(basename(src)).into_os_string())]
        } else {
            vec![(src.clone(), dst.clone())]
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

    // Invocation-wide validation: directory sources and self-copy
    for (src, dst) in &pairs {
        let src_path = Path::new(src);
        if let Ok(meta) = fs::metadata(src_path) {
            if meta.is_dir() {
                eprintln!("error: {} is a directory", os_display(src));
                std::process::exit(1);
            }
        }
        if let (Ok(s), Ok(d)) = (fs::canonicalize(src_path), fs::canonicalize(Path::new(dst))) {
            if s == d {
                eprintln!(
                    "error: '{}' and '{}' are the same file",
                    os_display(src),
                    os_display(dst)
                );
                std::process::exit(1);
            }
        }
    }

    // Perform copies in operand order; continue on per-source failure
    let mut had_error = false;
    for (src, dst) in &pairs {
        if let Err(e) = copy_path(Path::new(src), Path::new(dst), force) {
            eprintln!("error: {}: {}", os_display(src), e);
            had_error = true;
        }
    }

    if had_error {
        std::process::exit(1);
    }
}

fn parse_operands(args: &[OsString]) -> Result<(Vec<OsString>, bool), String> {
    let mut operands = Vec::new();
    let mut force = false;
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
                return Err(format!(
                    "error: unknown option '{}'",
                    os_display(arg.as_os_str())
                ));
            }
        }
        operands.push(arg.clone());
    }

    Ok((operands, force))
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

fn copy_path(src: &Path, dst: &Path, force: bool) -> io::Result<()> {
    let mut src_file = fs::File::open(src)?;
    let mode = src_file.metadata()?.permissions().mode() & 0o777;

    // Inspect destination via lstat
    if let Ok(dst_meta) = fs::symlink_metadata(dst) {
        if dst_meta.is_dir() {
            return Err(io::Error::new(
                io::ErrorKind::Unsupported,
                format!("{}: is a directory", dst.display()),
            ));
        }
        if dst_meta.file_type().is_symlink() {
            match fs::metadata(dst) {
                Ok(target) => {
                    if !target.is_file() {
                        return Err(io::Error::new(
                            io::ErrorKind::Unsupported,
                            format!("{}: not a regular file", dst.display()),
                        ));
                    }
                    let mut dst_file = fs::OpenOptions::new()
                        .write(true)
                        .truncate(true)
                        .open(dst)?;
                    io::copy(&mut src_file, &mut dst_file)?;
                    return Ok(());
                }
                Err(_) => {
                    // Dangling symlink
                    if !force {
                        return Err(io::Error::new(
                            io::ErrorKind::NotFound,
                            format!("{}: dangling symlink", dst.display()),
                        ));
                    }
                    fs::remove_file(dst)?;
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
                    return Err(e);
                }
                fs::remove_file(dst)?;
            }
            fs::OpenOptions::new()
                .write(true)
                .create(true)
                .truncate(true)
                .mode(mode)
                .open(dst)?
        }
        Err(e) => return Err(e),
    };

    io::copy(&mut src_file, &mut dst_file)?;
    Ok(())
}
