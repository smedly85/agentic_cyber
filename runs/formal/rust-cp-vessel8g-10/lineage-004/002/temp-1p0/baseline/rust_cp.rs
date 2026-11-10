use std::ffi::OsString;
use std::fs;
use std::io;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::ffi::OsStrExt;
use std::path::Path;
use std::process;

fn main() {
    let args: Vec<OsString> = std::env::args_os().skip(1).collect();

    let (operands, force) = match parse_operands(&args) {
        Ok(o) => o,
        Err(msg) => {
            eprintln!("{}", msg);
            process::exit(1);
        }
    };

    // Build (source, dest) pairs
    let pairs: Vec<(OsString, OsString)>;
    if operands.len() == 2 {
        let src = &operands[0];
        let dst = &operands[1];
        if Path::new(dst).is_dir() {
            let basename = Path::new(src)
                .file_name()
                .map(|f| f.to_owned())
                .unwrap_or_else(|| src.clone());
            let effective_dest = Path::new(dst).join(&basename);
            pairs = vec![(src.clone(), effective_dest.into_os_string())];
        } else {
            pairs = vec![(src.clone(), dst.clone())];
        }
    } else {
        let dest_dir = operands[operands.len() - 1].clone();
        if !Path::new(&dest_dir).is_dir() {
            eprintln!("error: {} is not an existing directory", dest_dir.to_string_lossy());
            process::exit(1);
        }
        pairs = operands[..operands.len() - 1]
            .iter()
            .map(|src| {
                let basename = Path::new(src)
                    .file_name()
                    .map(|f| f.to_owned())
                    .unwrap_or_else(|| src.clone());
                let dest = Path::new(&dest_dir).join(&basename);
                (src.clone(), dest.into_os_string())
            })
            .collect();
    }

    // Execute copies in operand order; continue after per-source failures
    let mut any_failed = false;
    for (src, dst) in &pairs {
        if let Err(e) = copy_path(Path::new(src), Path::new(dst), force) {
            eprintln!(
                "{}: {}: {}",
                src.to_string_lossy(),
                dst.to_string_lossy(),
                e
            );
            any_failed = true;
        }
    }

    process::exit(if any_failed { 1 } else { 0 });
}

fn parse_operands(args: &[OsString]) -> Result<(Vec<OsString>, bool), String> {
    let mut operands: Vec<OsString> = Vec::new();
    let mut after_ddash = false;
    let mut force = false;

    for arg in args {
        if !after_ddash && arg == "--" {
            after_ddash = true;
            continue;
        }
        if !after_ddash && arg != "-" && arg.as_bytes().first() == Some(&b'-') {
            if arg == "-f" || arg == "--force" {
                force = true;
                continue;
            }
            return Err(format!("unknown option: {}", arg.to_string_lossy()));
        }
        operands.push(arg.clone());
    }

    if operands.len() < 2 {
        return Err("missing operand".to_string());
    }

    Ok((operands, force))
}

/// Core filesystem copy operation: copies a regular file from `source` to `dest`.
/// Follows symlinks on both sides, detects self-copy by device+inode,
/// retains existing dest permissions on overwrite, applies source permissions
/// (masked by umask) on creation.
fn copy_path(source: &Path, dest: &Path, force: bool) -> io::Result<()> {
    // Validate source: must resolve to a regular file
    let source_meta = fs::metadata(source)?;
    if !source_meta.is_file() {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "source is not a regular file",
        ));
    }

    // Validate destination and determine if it exists as a regular file
    let dest_is_file: bool;
    let dst_meta: Option<fs::Metadata>;

    match fs::metadata(dest) {
        Ok(m) if m.is_file() => {
            dest_is_file = true;
            dst_meta = Some(m);
        }
        Ok(m) if m.is_dir() => {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "destination is a directory",
            ));
        }
        Ok(_) => {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "destination is not a regular file",
            ));
        }
        Err(ref e) if e.kind() == io::ErrorKind::NotFound => {
            dest_is_file = false;
            dst_meta = None;
            // Distinguish dangling symlink from non-existent path
            if fs::symlink_metadata(dest).is_ok() {
                return Err(io::Error::new(
                    io::ErrorKind::InvalidInput,
                    "destination is a dangling symlink",
                ));
            }
        }
        Err(e) => return Err(e),
    }

    // Self-copy detection via device + inode (catches hard links and aliases)
    if let Some(dm) = &dst_meta {
        if source_meta.dev() == dm.dev() && source_meta.ino() == dm.ino() {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "source and destination are the same file",
            ));
        }
    }

    // Open source for reading
    let mut src_file = fs::File::open(source)?;
    let source_perms = source_meta.mode() & 0o777;

    // Open or create destination
    let mut dst_file = if dest_is_file {
        match fs::OpenOptions::new().write(true).truncate(true).open(dest) {
            Ok(f) => f,
            Err(e) if force => {
                fs::remove_file(dest).map_err(|_| e)?;
                fs::OpenOptions::new()
                    .write(true)
                    .create(true)
                    .mode(source_perms)
                    .open(dest)?
            }
            Err(e) => return Err(e),
        }
    } else {
        fs::OpenOptions::new()
            .write(true)
            .create(true)
            .mode(source_perms)
            .open(dest)?
    };

    // Copy contents
    io::copy(&mut src_file, &mut dst_file)?;

    Ok(())
}
