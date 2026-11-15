use std::ffi::OsString;
use std::fs;
use std::io;
use std::io::BufRead;
use std::io::Write;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::fs::DirBuilderExt;
use std::os::unix::fs::symlink;
use std::os::unix::ffi::OsStrExt;
use std::path::Path;
use std::process;

enum CopyResult {
    Success,
    Declined,
    Failed(String),
}

fn main() {
    let args: Vec<OsString> = std::env::args_os().skip(1).collect();

    let (operands, force, interactive, recursive) = match parse_operands(&args) {
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

    let mut any_failed = false;
    for (src, dst) in &pairs {
        match copy_path(Path::new(src), Path::new(dst), force, interactive, recursive) {
            CopyResult::Success => {}
            CopyResult::Declined => {
                any_failed = true;
            }
            CopyResult::Failed(msg) => {
                eprintln!(
                    "{}: {}: {}",
                    src.to_string_lossy(),
                    dst.to_string_lossy(),
                    msg
                );
                any_failed = true;
            }
        }
    }

    process::exit(if any_failed { 1 } else { 0 });
}

fn parse_operands(args: &[OsString]) -> Result<(Vec<OsString>, bool, bool, bool), String> {
    let mut operands: Vec<OsString> = Vec::new();
    let mut after_ddash = false;
    let mut force = false;
    let mut interactive = false;
    let mut recursive = false;

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
            if arg == "-i" || arg == "--interactive" {
                interactive = true;
                continue;
            }
            if arg == "-r" || arg == "--recursive" {
                recursive = true;
                continue;
            }
            return Err(format!("unknown option: {}", arg.to_string_lossy()));
        }
        operands.push(arg.clone());
    }

    if operands.len() < 2 {
        return Err("missing operand".to_string());
    }

    Ok((operands, force, interactive, recursive))
}

fn prompt_interactive(dest: &Path) -> bool {
    eprint!("overwrite {}? ", dest.to_string_lossy());
    io::stderr().flush().ok();
    let mut line = String::new();
    match io::stdin().lock().read_line(&mut line) {
        Ok(0) => false,
        Ok(_) => {
            let b = line.as_bytes();
            b.first() == Some(&b'y') || b.first() == Some(&b'Y')
        }
        Err(_) => false,
    }
}

fn copy_path(source: &Path, dest: &Path, force: bool, interactive: bool, recursive: bool) -> CopyResult {
    let fail = |e: io::Error| CopyResult::Failed(e.to_string());

    let source_lstat = match fs::symlink_metadata(source) {
        Ok(m) => m,
        Err(e) => return fail(e),
    };

    if source_lstat.file_type().is_symlink() && recursive {
        return recreate_symlink(source, dest, force, interactive);
    }

    let source_meta = match fs::metadata(source) {
        Ok(m) => m,
        Err(e) => return fail(e),
    };

    if source_meta.is_dir() {
        if !recursive {
            return CopyResult::Failed(format!("{}: source is a directory", source.display()));
        }
        return copy_dir(source, dest, force, interactive);
    }

    if !source_meta.is_file() {
        return CopyResult::Failed("source is not a regular file".to_string());
    }

    let dest_is_file: bool;
    let dst_meta: Option<fs::Metadata>;

    match fs::metadata(dest) {
        Ok(m) if m.is_file() => {
            dest_is_file = true;
            dst_meta = Some(m);
        }
        Ok(m) if m.is_dir() => {
            return CopyResult::Failed("destination is a directory".to_string());
        }
        Ok(_) => {
            return CopyResult::Failed("destination is not a regular file".to_string());
        }
        Err(ref e) if e.kind() == io::ErrorKind::NotFound => {
            dest_is_file = false;
            dst_meta = None;
            if fs::symlink_metadata(dest).is_ok() {
                return CopyResult::Failed("destination is a dangling symlink".to_string());
            }
        }
        Err(e) => return fail(e),
    }

    if let Some(dm) = &dst_meta {
        if source_meta.dev() == dm.dev() && source_meta.ino() == dm.ino() {
            return CopyResult::Failed("source and destination are the same file".to_string());
        }
    }

    if dest_is_file && interactive {
        if !prompt_interactive(dest) {
            return CopyResult::Declined;
        }
    }

    let mut src_file = match fs::File::open(source) {
        Ok(f) => f,
        Err(e) => return fail(e),
    };
    let source_perms = source_meta.mode() & 0o777;

    let mut dst_file = if dest_is_file {
        match fs::OpenOptions::new().write(true).truncate(true).open(dest) {
            Ok(f) => f,
            Err(e) if force => {
                if fs::remove_file(dest).is_err() {
                    return fail(e);
                }
                match fs::OpenOptions::new()
                    .write(true)
                    .create(true)
                    .mode(source_perms)
                    .open(dest)
                {
                    Ok(f) => f,
                    Err(e) => return fail(e),
                }
            }
            Err(e) => return fail(e),
        }
    } else {
        match fs::OpenOptions::new()
            .write(true)
            .create(true)
            .mode(source_perms)
            .open(dest)
        {
            Ok(f) => f,
            Err(e) => return fail(e),
        }
    };

    if let Err(e) = io::copy(&mut src_file, &mut dst_file) {
        return fail(e);
    }

    CopyResult::Success
}

fn is_copy_into_self(source: &Path, dest: &Path) -> bool {
    let canonical_source = match source.canonicalize() {
        Ok(p) => p,
        Err(_) => return false,
    };
    if fs::symlink_metadata(dest).is_ok() {
        let canonical_dest = match dest.canonicalize() {
            Ok(p) => p,
            Err(_) => return false,
        };
        canonical_dest == canonical_source || canonical_dest.starts_with(&canonical_source)
    } else {
        let parent = match dest.parent() {
            Some(p) => p,
            None => return false,
        };
        let canonical_parent = match parent.canonicalize() {
            Ok(p) => p,
            Err(_) => return false,
        };
        canonical_parent == canonical_source || canonical_parent.starts_with(&canonical_source)
    }
}

fn recreate_symlink(source: &Path, dest: &Path, force: bool, interactive: bool) -> CopyResult {
    let target = match fs::read_link(source) {
        Ok(t) => t,
        Err(e) => return CopyResult::Failed(e.to_string()),
    };

    if let Ok(dest_meta) = fs::symlink_metadata(dest) {
        if dest_meta.is_dir() {
            return CopyResult::Failed(format!("{}: destination is a directory", dest.display()));
        }
        if interactive {
            if !prompt_interactive(dest) {
                return CopyResult::Declined;
            }
        }
        if let Err(e) = fs::remove_file(dest) {
            if !force {
                return CopyResult::Failed(e.to_string());
            }
            if let Err(e) = fs::remove_file(dest) {
                return CopyResult::Failed(e.to_string());
            }
        }
    }

    match symlink(&target, dest) {
        Ok(()) => CopyResult::Success,
        Err(e) => CopyResult::Failed(e.to_string()),
    }
}

fn copy_dir(source: &Path, dest: &Path, force: bool, interactive: bool) -> CopyResult {
    if is_copy_into_self(source, dest) {
        return CopyResult::Failed(format!(
            "{}: cannot copy a directory into itself or a descendant",
            source.display()
        ));
    }

    match fs::symlink_metadata(dest) {
        Ok(m) => {
            if !m.is_dir() {
                return CopyResult::Failed(format!("{}: destination is not a directory", dest.display()));
            }
        }
        Err(ref e) if e.kind() == io::ErrorKind::NotFound => {
            let src_meta = match fs::metadata(source) {
                Ok(m) => m,
                Err(e) => return CopyResult::Failed(e.to_string()),
            };
            let mode = src_meta.mode() & 0o777;
            if let Err(e) = fs::DirBuilder::new().mode(mode).create(dest) {
                return CopyResult::Failed(e.to_string());
            }
        }
        Err(e) => return CopyResult::Failed(e.to_string()),
    }

    let mut entries: Vec<fs::DirEntry> = match fs::read_dir(source) {
        Ok(rd) => rd.filter_map(|e| e.ok()).collect(),
        Err(e) => return CopyResult::Failed(e.to_string()),
    };
    entries.sort_by_key(|e| e.file_name());

    let mut any_failed = false;
    for entry in entries {
        let child_src = entry.path();
        let child_dest = dest.join(entry.file_name());

        let child_st = match fs::symlink_metadata(&child_src) {
            Ok(m) => m,
            Err(_) => { any_failed = true; continue; }
        };

        let result = if child_st.file_type().is_symlink() {
            recreate_symlink(&child_src, &child_dest, force, interactive)
        } else if child_st.is_dir() {
            copy_dir(&child_src, &child_dest, force, interactive)
        } else if child_st.is_file() {
            copy_path(&child_src, &child_dest, force, interactive, true)
        } else {
            CopyResult::Failed(format!("{}: unsupported file type", child_src.display()))
        };

        match result {
            CopyResult::Success => {}
            _ => { any_failed = true; }
        }
    }

    if any_failed {
        return CopyResult::Failed("one or more entries failed to copy".to_string());
    }
    CopyResult::Success
}
