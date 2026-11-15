use std::env;
use std::ffi::OsString;
use std::fs;
use std::io::{self, Read, Write};
use std::os::unix::fs::{MetadataExt, OpenOptionsExt, PermissionsExt};
use std::path::{Path, PathBuf};
use std::process;

fn is_same_file(a: &Path, b: &Path) -> bool {
    match (fs::metadata(a), fs::metadata(b)) {
        (Ok(ma), Ok(mb)) => ma.dev() == mb.dev() && ma.ino() == mb.ino(),
        _ => false,
    }
}

fn copy_path(src: &Path, dst: &Path) -> io::Result<()> {
    let src_meta = fs::metadata(src)?;
    if !src_meta.is_file() {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            format!("{}: not a regular file", src.display()),
        ));
    }

    match fs::symlink_metadata(dst) {
        Ok(lmeta) => {
            if lmeta.is_dir() {
                return Err(io::Error::new(
                    io::ErrorKind::InvalidInput,
                    format!("{}: is a directory", dst.display()),
                ));
            }
            if lmeta.is_symlink() {
                match fs::metadata(dst) {
                    Ok(meta) => {
                        if !meta.is_file() {
                            return Err(io::Error::new(
                                io::ErrorKind::InvalidInput,
                                format!("{}: destination is not a regular file", dst.display()),
                            ));
                        }
                    }
                    Err(_) => {
                        return Err(io::Error::new(
                            io::ErrorKind::NotFound,
                            format!("{}: dangling symlink", dst.display()),
                        ));
                    }
                }
            }
        }
        Err(e) if e.kind() == io::ErrorKind::NotFound => {}
        Err(e) => return Err(e),
    }

    if is_same_file(src, dst) {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            format!("{} and {}: are the same file", src.display(), dst.display()),
        ));
    }

    let src_file = fs::File::open(src)?;
    let dst_exists = fs::symlink_metadata(dst).is_ok();
    let dst_file = if dst_exists {
        fs::OpenOptions::new()
            .write(true)
            .truncate(true)
            .open(dst)?
    } else {
        let mode = src_meta.permissions().mode();
        fs::OpenOptions::new()
            .write(true)
            .create(true)
            .mode(mode)
            .open(dst)?
    };

    let mut reader = src_file;
    let mut writer = dst_file;
    io::copy(&mut reader, &mut writer)?;
    writer.flush()?;

    Ok(())
}

fn main() {
    let args: Vec<OsString> = env::args_os().skip(1).collect();

    let mut operands: Vec<OsString> = Vec::new();
    let mut after_ddash = false;

    for arg in &args {
        if !after_ddash && *arg == OsString::from("--") {
            after_ddash = true;
            continue;
        }
        if !after_ddash {
            let s = arg.to_string_lossy();
            if s.len() > 1 && s.starts_with('-') {
                eprintln!("rust_cp: unknown option: {}", s);
                process::exit(1);
            }
        }
        operands.push(arg.clone());
    }

    if operands.len() < 2 {
        eprintln!("rust_cp: missing operand");
        process::exit(1);
    }

    let n = operands.len();
    let last = &operands[n - 1];
    let last_path = Path::new(last);

    let pairs: Vec<(PathBuf, PathBuf)> = if n == 2 {
        let src = PathBuf::from(&operands[0]);
        let dst = if last_path.is_dir() {
            last_path.join(src.file_name().unwrap_or_else(|| src.as_os_str()))
        } else {
            last_path.to_path_buf()
        };
        vec![(src, dst)]
    } else {
        if !last_path.is_dir() {
            eprintln!("rust_cp: {}: not a directory", last.to_string_lossy());
            process::exit(1);
        }
        (0..n - 1)
            .map(|i| {
                let src = PathBuf::from(&operands[i]);
                let filename = src.file_name().unwrap_or_else(|| src.as_os_str());
                let dst = last_path.join(filename);
                (src, dst)
            })
            .collect()
    };

    let mut had_error = false;
    for (src, dst) in &pairs {
        if let Err(e) = copy_path(src, dst) {
            eprintln!("rust_cp: {} -> {}: {}", src.display(), dst.display(), e);
            had_error = true;
        }
    }

    if had_error {
        process::exit(1);
    }
}
