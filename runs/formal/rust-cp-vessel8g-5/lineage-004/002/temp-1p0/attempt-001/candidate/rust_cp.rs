use std::ffi::OsString;
use std::fs;
use std::io;
use std::io::BufRead;
use std::io::Write;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
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

    let (operands, force, interactive) = match parse_operands(&args) {
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
        match copy_path(Path::new(src), Path::new(dst), force, interactive) {
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

fn parse_operands(args: &[OsString]) -> Result<(Vec<OsString>, bool, bool), String> {
    let mut operands: Vec<OsString> = Vec::new();
    let mut after_ddash = false;
    let mut force = false;
    let mut interactive = false;

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
            return Err(format!("unknown option: {}", arg.to_string_lossy()));
        }
        operands.push(arg.clone());
    }

    if operands.len() < 2 {
        return Err("missing operand".to_string());
    }

    Ok((operands, force, interactive))
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

fn copy_path(source: &Path, dest: &Path, force: bool, interactive: bool) -> CopyResult {
    let fail = |e: io::Error| CopyResult::Failed(e.to_string());

    let source_meta = match fs::metadata(source) {
        Ok(m) => m,
        Err(e) => return fail(e),
    };
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
