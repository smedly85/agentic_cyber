use std::ffi::OsString;
use std::io::{BufRead, Write};
use std::fs;
use std::os::unix::ffi::OsStrExt;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process;

#[derive(PartialEq)]
enum OverwritePolicy {
    Default,
    Force,
    Interactive,
}

fn main() {
    let args: Vec<OsString> = std::env::args_os().skip(1).collect();

    let mut operands: Vec<OsString> = Vec::new();
    let mut after_separator = false;
    let mut policy = OverwritePolicy::Default;

    for arg in &args {
        if !after_separator {
            if arg.as_bytes() == b"--" {
                after_separator = true;
                continue;
            }
            let bytes = arg.as_bytes();
            if bytes.len() > 1 && bytes[0] == b'-' {
                let arg_str = String::from_utf8_lossy(bytes);
                if arg_str == "-f" || arg_str == "--force" {
                    policy = OverwritePolicy::Force;
                    continue;
                }
                if arg_str == "-i" || arg_str == "--interactive" {
                    policy = OverwritePolicy::Interactive;
                    continue;
                }
                eprintln!(
                    "mv: unrecognized option: {}",
                    arg_str
                );
                process::exit(1);
            }
        }
        operands.push(arg.clone());
    }

    if operands.len() < 2 {
        eprintln!("mv: missing destination");
        process::exit(1);
    }

    let is_multi = operands.len() > 2;

    if is_multi {
        let last = Path::new(operands.last().unwrap());
        match fs::symlink_metadata(last) {
            Ok(m) if m.is_dir() => {}
            Ok(_) => {
                eprintln!("mv: target '{}': not a directory", last.to_string_lossy());
                process::exit(1);
            }
            Err(e) => {
                eprintln!(
                    "mv: cannot access '{}': {}",
                    last.to_string_lossy(),
                    e
                );
                process::exit(1);
            }
        }
    }

    let mut moves: Vec<(PathBuf, PathBuf)> = Vec::new();

    if is_multi {
        let dir = Path::new(operands.last().unwrap());
        for src in &operands[..operands.len() - 1] {
            let src_path = PathBuf::from(src);
            let base = src_path.file_name().unwrap_or(src.as_os_str());
            let dest = dir.join(base);
            moves.push((src_path, dest));
        }
    } else {
        let src = PathBuf::from(&operands[0]);
        let dest_raw = PathBuf::from(&operands[1]);
        let dest = if fs::symlink_metadata(&dest_raw)
            .map(|m| m.is_dir())
            .unwrap_or(false)
        {
            let base = src.file_name().unwrap_or(src.as_os_str());
            dest_raw.join(base)
        } else {
            dest_raw
        };
        moves.push((src, dest));
    }

    let mut had_error = false;

    for (src, dest) in &moves {
        if let Err(detail) = validate_and_move(src, dest, &policy) {
            eprintln!("mv: {}", detail);
            had_error = true;
        }
    }

    if had_error {
        process::exit(1);
    }
}

fn prompt_overwrite(dest: &Path) -> bool {
    eprint!("mv: overwrite '{}'? ", dest.to_string_lossy());
    let _ = std::io::stderr().flush();
    let mut line = String::new();
    match std::io::stdin().lock().read_line(&mut line) {
        Ok(0) => false,
        Ok(_) => {
            let _ = line.pop(); // remove trailing newline
            matches!(line.chars().next(), Some('y') | Some('Y'))
        }
        Err(_) => false,
    }
}

fn validate_and_move(src: &Path, dest: &Path, policy: &OverwritePolicy) -> Result<(), String> {
    let src_meta = fs::symlink_metadata(src)
        .map_err(|e| format!("cannot stat '{}': {}", src.to_string_lossy(), e))?;

    if let (Ok(sr), Ok(dr)) = (fs::canonicalize(src), fs::canonicalize(dest)) {
        if sr == dr {
            return Err(format!(
                "'{}' and '{}' are the same file",
                src.to_string_lossy(),
                dest.to_string_lossy()
            ));
        }
    }

    let dest_meta = match fs::symlink_metadata(dest) {
        Ok(m) => m,
        Err(_) => {
            return move_path(src, dest).map_err(|e| {
                format!(
                    "cannot move '{}' to '{}': {}",
                    src.to_string_lossy(),
                    dest.to_string_lossy(),
                    e
                )
            });
        }
    };

    if src_meta.is_dir() {
        if !dest_meta.is_dir() {
            return Err(format!(
                "cannot move directory '{}' to non-directory '{}'",
                src.to_string_lossy(),
                dest.to_string_lossy()
            ));
        }
        match fs::read_dir(dest) {
            Ok(mut rd) => {
                if rd.next().is_some() {
                    return Err(format!(
                        "cannot move directory '{}' into non-empty directory '{}'",
                        src.to_string_lossy(),
                        dest.to_string_lossy()
                    ));
                }
            }
            Err(e) => {
                return Err(format!(
                    "cannot read directory '{}': {}",
                    dest.to_string_lossy(),
                    e
                ));
            }
        }
    } else if dest_meta.is_dir() {
        return Err(format!(
            "cannot replace directory '{}' with non-directory '{}'",
            dest.to_string_lossy(),
            src.to_string_lossy()
        ));
    }

    // Destination exists and would be replaced.
    if *policy == OverwritePolicy::Interactive {
        if !prompt_overwrite(dest) {
            return Err(format!(
                "not overwriting '{}'",
                dest.to_string_lossy()
            ));
        }
    }

    if dest_meta.file_type().is_file() {
        let mode = dest_meta.permissions().mode();
        if mode & 0o222 == 0 && *policy == OverwritePolicy::Default {
            return Err(format!(
                "cannot overwrite write-protected regular file '{}'",
                dest.to_string_lossy()
            ));
        }
    }

    move_path(src, dest).map_err(|e| {
        format!(
            "cannot move '{}' to '{}': {}",
            src.to_string_lossy(),
            dest.to_string_lossy(),
            e
        )
    })
}

fn move_path(source: &Path, destination: &Path) -> std::io::Result<()> {
    fs::rename(source, destination)
}
