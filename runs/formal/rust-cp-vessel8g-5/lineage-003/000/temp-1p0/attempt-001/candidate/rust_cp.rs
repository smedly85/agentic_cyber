use std::env;
use std::ffi::OsString;
use std::fs;
use std::io::{self, Write};
use std::os::unix::fs::{MetadataExt, OpenOptionsExt, PermissionsExt};
use std::path::{Path, PathBuf};
use std::process;

fn copy_path(src: &Path, dest: &Path) -> Result<(), String> {
    let src_meta = fs::metadata(src).map_err(|e| {
        format!("{}: {}", src.to_string_lossy(), e)
    })?;

    if src_meta.is_dir() {
        return Err(format!("{}: is a directory", src.to_string_lossy()));
    }

    let dest_is_new = match fs::symlink_metadata(dest) {
        Ok(meta) => {
            if meta.is_symlink() {
                let resolved = fs::metadata(dest).map_err(|e| {
                    format!("{}: {}", dest.to_string_lossy(), e)
                })?;
                if resolved.is_dir() {
                    return Err(format!("{}: is a directory", dest.to_string_lossy()));
                }
            } else if meta.is_dir() {
                return Err(format!("{}: is a directory", dest.to_string_lossy()));
            }
            false
        }
        Err(ref e) if e.kind() == io::ErrorKind::NotFound => true,
        Err(e) => {
            return Err(format!("{}: {}", dest.to_string_lossy(), e));
        }
    };

    if !dest_is_new {
        let dest_meta = fs::metadata(dest).map_err(|e| {
            format!("{}: {}", dest.to_string_lossy(), e)
        })?;
        if src_meta.dev() == dest_meta.dev() && src_meta.ino() == dest_meta.ino() {
            return Err(format!(
                "{} and {} are the same file",
                src.to_string_lossy(),
                dest.to_string_lossy()
            ));
        }
    }

    let src_perm = src_meta.permissions().mode();

    if dest_is_new {
        let mut file = fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(src_perm & 0o777)
            .open(dest)
            .map_err(|e| format!("{}: {}", dest.to_string_lossy(), e))?;

        let mut src_file = fs::File::open(src).map_err(|e| {
            format!("{}: {}", src.to_string_lossy(), e)
        })?;

        io::copy(&mut src_file, &mut file).map_err(|e| {
            format!("{}: {}", dest.to_string_lossy(), e)
        })?;

        file.flush().map_err(|e| {
            format!("{}: {}", dest.to_string_lossy(), e)
        })?;
    } else {
        let mut file = fs::OpenOptions::new()
            .write(true)
            .truncate(true)
            .open(dest)
            .map_err(|e| format!("{}: {}", dest.to_string_lossy(), e))?;

        let mut src_file = fs::File::open(src).map_err(|e| {
            format!("{}: {}", src.to_string_lossy(), e)
        })?;

        io::copy(&mut src_file, &mut file).map_err(|e| {
            format!("{}: {}", dest.to_string_lossy(), e)
        })?;

        file.flush().map_err(|e| {
            format!("{}: {}", dest.to_string_lossy(), e)
        })?;
    }

    Ok(())
}

fn resolve_targets(operands: &[OsString]) -> Result<Vec<(PathBuf, PathBuf)>, String> {
    let last = Path::new(&operands[operands.len() - 1]);

    if operands.len() == 2 {
        let src = PathBuf::from(&operands[0]);
        let dest = if last.is_dir() {
            let basename = src.file_name().ok_or_else(|| {
                format!("{}: cannot determine basename", operands[0].to_string_lossy())
            })?;
            last.join(basename)
        } else {
            PathBuf::from(&operands[1])
        };
        Ok(vec![(src, dest)])
    } else {
        if !last.is_dir() {
            return Err(format!(
                "{}: not a directory",
                operands[operands.len() - 1].to_string_lossy()
            ));
        }
        let mut targets = Vec::new();
        for s in &operands[..operands.len() - 1] {
            let src = PathBuf::from(s);
            let basename = src.file_name().ok_or_else(|| {
                format!("{}: cannot determine basename", s.to_string_lossy())
            })?;
            let basename = std::ffi::OsString::from(basename);
            targets.push((src, last.join(&basename)));
        }
        Ok(targets)
    }
}

fn main() {
    let args: Vec<OsString> = std::env::args_os().skip(1).collect();

    let mut operands: Vec<OsString> = Vec::new();
    let mut saw_double_dash = false;

    for arg in args {
        if !saw_double_dash && arg.len() > 1 && arg[0] == b'-' {
            if &arg[..] == b"--" {
                saw_double_dash = true;
                continue;
            }
            eprintln!("unknown option: {}", arg.to_string_lossy());
            process::exit(1);
        } else {
            operands.push(arg);
        }
    }

    if operands.is_empty() {
        eprintln!("missing operand");
        process::exit(1);
    }

    if operands.len() == 1 {
        eprintln!("missing destination operand");
        process::exit(1);
    }

    let targets = match resolve_targets(&operands) {
        Ok(t) => t,
        Err(e) => {
            eprintln!("{}", e);
            process::exit(1);
        }
    };

    let mut failed = false;
    for (src, dest) in targets {
        if let Err(e) = copy_path(&src, &dest) {
            eprintln!("{}", e);
            failed = true;
        }
    }

    if failed {
        process::exit(1);
    }
}
