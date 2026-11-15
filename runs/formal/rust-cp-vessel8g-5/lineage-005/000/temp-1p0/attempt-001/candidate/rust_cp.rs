use std::ffi::OsString;
use std::fs::{self, File, OpenOptions};
use std::io::{self, Write};
use std::os::unix::ffi::OsStrExt;
use std::os::unix::fs::{MetadataExt, OpenOptionsExt, PermissionsExt};
use std::path::{Path, PathBuf};
use std::process;

fn main() {
    let args: Vec<OsString> = std::env::args_os().collect();

    let mut operands: Vec<OsString> = Vec::new();
    let mut after_ddash = false;

    for arg in &args[1..] {
        if after_ddash {
            operands.push(arg.clone());
            continue;
        }
        if arg.as_bytes() == b"--" {
            after_ddash = true;
            continue;
        }
        if arg.as_bytes().len() > 1 && arg.as_bytes()[0] == b'-' {
            eprintln!("rust_cp: unknown option: {}", arg.to_string_lossy());
            process::exit(1);
        }
        operands.push(arg.clone());
    }

    if operands.len() < 2 {
        eprintln!("rust_cp: missing operand");
        process::exit(1);
    }

    let multi = operands.len() > 2;

    if multi {
        let dir = Path::new(operands.last().unwrap());
        if !dir.is_dir() {
            eprintln!("rust_cp: {}: not a directory", dir.to_string_lossy());
            process::exit(1);
        }
    }

    let source_count = if multi { operands.len() - 1 } else { 1 };
    let mut any_failed = false;

    for i in 0..source_count {
        let src = Path::new(operands[i].as_os_str());
        let effective_dest: PathBuf;

        if multi {
            let dir = Path::new(operands[operands.len() - 1].as_os_str());
            let basename = src.file_name().unwrap_or(src.as_os_str());
            effective_dest = dir.join(basename);
        } else {
            let dest = Path::new(operands[1].as_os_str());
            if dest.is_dir() {
                let basename = src.file_name().unwrap_or(src.as_os_str());
                effective_dest = dest.join(basename);
            } else {
                effective_dest = dest.to_path_buf();
            }
        }

        if let Err(e) = copy_path(src, &effective_dest) {
            eprintln!("rust_cp: {}: {}", src.to_string_lossy(), e);
            any_failed = true;
        }
    }

    if any_failed {
        process::exit(1);
    }
}

fn copy_path(src: &Path, dest: &Path) -> io::Result<()> {
    let src_resolved = fs::canonicalize(src)?;
    let src_meta = fs::metadata(&src_resolved)?;

    if src_meta.is_dir() {
        return Err(io::Error::new(io::ErrorKind::InvalidInput, "is a directory"));
    }
    if !src_meta.is_file() {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "is not a regular file",
        ));
    }

    let src_mode = src_meta.permissions().mode() & 0o777;

    let dest_resolved = match fs::canonicalize(dest) {
        Ok(p) => p,
        Err(_) => {
            if let Ok(link_meta) = fs::symlink_metadata(dest) {
                if link_meta.file_type().is_symlink() {
                    return Err(io::Error::new(
                        io::ErrorKind::InvalidInput,
                        "destination is a dangling symlink",
                    ));
                }
            }
            let mut src_file = File::open(&src_resolved)?;
            let mut dest_file = OpenOptions::new()
                .write(true)
                .create(true)
                .truncate(true)
                .mode(src_mode)
                .open(dest)?;
            io::copy(&mut src_file, &mut dest_file)?;
            dest_file.flush()?;
            return Ok(());
        }
    };

    let dest_meta = fs::metadata(&dest_resolved)?;
    if dest_meta.is_dir() {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "destination is a directory",
        ));
    }
    if !dest_meta.is_file() {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "destination is not a regular file",
        ));
    }

    if src_meta.dev() == dest_meta.dev() && src_meta.ino() == dest_meta.ino() {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "source and destination are the same file",
        ));
    }

    let mut src_file = File::open(&src_resolved)?;
    let mut dest_file = OpenOptions::new()
        .write(true)
        .truncate(true)
        .open(&dest_resolved)?;
    io::copy(&mut src_file, &mut dest_file)?;
    dest_file.flush()?;
    Ok(())
}
