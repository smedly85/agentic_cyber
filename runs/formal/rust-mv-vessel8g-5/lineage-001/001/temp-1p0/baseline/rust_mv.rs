use std::ffi::OsString;
use std::io;
use std::os::unix::ffi::OsStrExt;
use std::os::unix::fs::MetadataExt;
use std::path::{Path, PathBuf};

fn main() {
    let args: Vec<OsString> = std::env::args_os().skip(1).collect();

    let mut operands: Vec<OsString> = Vec::new();
    let mut after_ddash = false;

    for arg in &args {
        if !after_ddash {
            let bytes = arg.as_bytes();
            if bytes == b"--" {
                after_ddash = true;
                continue;
            }
            if bytes == b"-" {
                operands.push(arg.clone());
                continue;
            }
            if bytes.first() == Some(&b'-') && bytes.len() > 1 {
                eprintln!("rust_mv: unknown option: {}", arg.to_string_lossy());
                std::process::exit(1);
            }
        }
        operands.push(arg.clone());
    }

    if operands.len() < 2 {
        eprintln!("rust_mv: missing destination operand");
        std::process::exit(1);
    }

    let (sources, dest, multi) = if operands.len() == 2 {
        (vec![operands[0].clone()], operands[1].clone(), false)
    } else {
        let d = operands[operands.len() - 1].clone();
        if !Path::new(&d).is_dir() {
            eprintln!(
                "rust_mv: target '{}' is not a directory",
                d.to_string_lossy()
            );
            std::process::exit(1);
        }
        (operands[..operands.len() - 1].to_vec(), d, true)
    };

    let mut any_failed = false;

    for source in &sources {
        let src = Path::new(source);
        let name = src.file_name().unwrap_or(source.as_os_str());

        let effective_dest: PathBuf = if multi {
            Path::new(&dest).join(name)
        } else {
            let d = Path::new(&dest);
            if d.is_dir() {
                d.join(name)
            } else {
                d.to_path_buf()
            }
        };

        match move_path(src, &effective_dest) {
            Ok(()) => {}
            Err(e) => {
                eprintln!(
                    "rust_mv: cannot move '{}' to '{}': {}",
                    source.to_string_lossy(),
                    effective_dest.to_string_lossy(),
                    e
                );
                any_failed = true;
            }
        }
    }

    if any_failed {
        std::process::exit(1);
    }
}

fn move_path(source: &Path, destination: &Path) -> io::Result<()> {
    let src_meta = std::fs::symlink_metadata(source).map_err(|e| {
        io::Error::new(e.kind(), format!("'{}': {}", source.to_string_lossy(), e))
    })?;

    let src_is_dir = src_meta.file_type().is_dir();

    if let Ok(dest_meta) = std::fs::symlink_metadata(destination) {
        if src_meta.dev() == dest_meta.dev() && src_meta.ino() == dest_meta.ino() {
            return Err(io::Error::new(
                io::ErrorKind::AlreadyExists,
                format!(
                    "'{}' and '{}' are the same file",
                    source.to_string_lossy(),
                    destination.to_string_lossy()
                ),
            ));
        }

        let dest_is_dir = dest_meta.file_type().is_dir();

        if src_is_dir && !dest_is_dir {
            return Err(io::Error::new(
                io::ErrorKind::IsADirectory,
                format!(
                    "cannot move directory '{}' over non-directory '{}'",
                    source.to_string_lossy(),
                    destination.to_string_lossy()
                ),
            ));
        }
        if !src_is_dir && dest_is_dir {
            return Err(io::Error::new(
                io::ErrorKind::NotADirectory,
                format!(
                    "cannot move non-directory '{}' into directory '{}'",
                    source.to_string_lossy(),
                    destination.to_string_lossy()
                ),
            ));
        }
        if src_is_dir && dest_is_dir {
            let mut rd = std::fs::read_dir(destination)?;
            if rd.next().is_some() {
                return Err(io::Error::new(
                    io::ErrorKind::Other,
                    format!("directory '{}' is not empty", destination.to_string_lossy()),
                ));
            }
        }
    }

    if src_is_dir && is_proper_ancestor(source, destination) {
        return Err(io::Error::new(
            io::ErrorKind::Other,
            format!("cannot move directory '{}' into itself", source.to_string_lossy()),
        ));
    }

    std::fs::rename(source, destination)
}

fn is_proper_ancestor(ancestor: &Path, descendant: &Path) -> bool {
    let a = normalize(ancestor);
    let d = normalize(descendant);
    if a.is_empty() || d.len() <= a.len() {
        return false;
    }
    d[..a.len()] == a
}

fn normalize(p: &Path) -> Vec<OsString> {
    let mut out = Vec::new();
    for c in p.components() {
        match c {
            std::path::Component::CurDir => {}
            std::path::Component::ParentDir => {
                out.pop();
            }
            other => out.push(other.as_os_str().to_owned()),
        }
    }
    out
}
