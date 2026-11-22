use std::env;
use std::ffi::{OsStr, OsString};
use std::fs::File;
use std::io::{self, Read, Write};
use std::os::unix::ffi::OsStrExt;
use std::path::Path;
use std::process::exit;

#[derive(PartialEq)]
enum FilenameMode {
    Default,
    With,
    Without,
}

fn search_stream(
    input: &[u8],
    pattern: &[u8],
    prefix: Option<&[u8]>,
    out: &mut dyn Write,
) -> io::Result<bool> {
    let mut any_match = false;
    let mut line_start = 0;

    for i in 0..input.len() {
        if input[i] == 0x0A {
            let line = &input[line_start..i];
            if pattern.is_empty()
                || (pattern.len() <= line.len()
                    && line.windows(pattern.len()).any(|w| w == pattern))
            {
                if let Some(p) = prefix {
                    out.write_all(p)?;
                    out.write_all(b":")?;
                }
                out.write_all(line)?;
                out.write_all(b"\n")?;
                any_match = true;
            }
            line_start = i + 1;
        }
    }

    // Final unterminated line
    if line_start < input.len() {
        let line = &input[line_start..];
        if pattern.is_empty()
            || (pattern.len() <= line.len()
                && line.windows(pattern.len()).any(|w| w == pattern))
        {
            if let Some(p) = prefix {
                out.write_all(p)?;
                out.write_all(b":")?;
            }
            out.write_all(line)?;
            out.write_all(b"\n")?;
            any_match = true;
        }
    }

    Ok(any_match)
}

fn search_file_path(
    path: &Path,
    pattern: &[u8],
    prefix: Option<&[u8]>,
    out: &mut dyn Write,
) -> (bool, bool) {
    // Returns (any_match, any_error)
    let mut file = match File::open(path) {
        Ok(f) => f,
        Err(_) => {
            let mut err = io::stderr();
            let _ = err.write_all(b"rust_grep: ");
            let _ = err.write_all(path.as_os_str().as_bytes());
            let _ = err.write_all(b": cannot open\n");
            return (false, true);
        }
    };

    let mut input = Vec::new();
    if file.read_to_end(&mut input).is_err() {
        let mut err = io::stderr();
        let _ = err.write_all(b"rust_grep: ");
        let _ = err.write_all(path.as_os_str().as_bytes());
        let _ = err.write_all(b": read error\n");
        return (false, true);
    }

    match search_stream(&input, pattern, prefix, out) {
        Ok(m) => (m, false),
        Err(_) => (false, true),
    }
}

fn traverse_dir(
    dir: &OsStr,
    pattern: &[u8],
    use_prefix: bool,
    out: &mut dyn Write,
) -> (bool, bool) {
    // Returns (any_match, any_error)
    let mut any_match = false;
    let mut any_error = false;

    let rd = match std::fs::read_dir(dir) {
        Ok(r) => r,
        Err(_) => {
            let mut err = io::stderr();
            let _ = err.write_all(b"rust_grep: ");
            let _ = err.write_all(dir.as_bytes());
            let _ = err.write_all(b": cannot read directory\n");
            return (false, true);
        }
    };

    let mut names: Vec<OsString> = Vec::new();
    for entry in rd {
        match entry {
            Ok(e) => names.push(e.file_name()),
            Err(e) => {
                any_error = true;
                let mut err = io::stderr();
                let _ = err.write_all(b"rust_grep: ");
                let _ = err.write_all(dir.as_bytes());
                let _ = err.write_all(b": ");
                let _ = err.write_all(e.to_string().as_bytes());
                let _ = err.write_all(b"\n");
            }
        }
    }

    names.sort_by(|a, b| a.as_bytes().cmp(b.as_bytes()));

    for name in names {
        let full = Path::new(dir).join(&name);

        let meta = match std::fs::symlink_metadata(&full) {
            Ok(m) => m,
            Err(_) => {
                any_error = true;
                let mut err = io::stderr();
                let _ = err.write_all(b"rust_grep: ");
                let _ = err.write_all(full.as_os_str().as_bytes());
                let _ = err.write_all(b": cannot stat\n");
                continue;
            }
        };

        let ft = meta.file_type();
        if ft.is_symlink() {
            continue;
        }
        if ft.is_file() {
            let prefix_bytes: Vec<u8> = if use_prefix {
                full.as_os_str().as_bytes().to_vec()
            } else {
                Vec::new()
            };
            let (m, e) = search_file_path(
                &full,
                pattern,
                if use_prefix { Some(prefix_bytes.as_slice()) } else { None },
                out,
            );
            any_match = any_match || m;
            any_error = any_error || e;
        } else if ft.is_dir() {
            let (m, e) = traverse_dir(full.as_os_str(), pattern, use_prefix, out);
            any_match = any_match || m;
            any_error = any_error || e;
        }
    }

    (any_match, any_error)
}

fn main() {
    let args_os: Vec<OsString> = env::args_os().collect();
    let args: &[OsString] = if args_os.len() > 1 { &args_os[1..] } else { &[] };

    let mut pattern: Option<Vec<u8>> = None;
    let mut files: Vec<OsString> = Vec::new();
    let mut after_ddash = false;
    let mut filename_mode = FilenameMode::Default;
    let mut recursive = false;

    for arg in args {
        let bytes: &[u8] = arg.as_bytes();
        if !after_ddash {
            if bytes == b"--" {
                after_ddash = true;
                continue;
            }
            if bytes == b"--with-filename" {
                filename_mode = FilenameMode::With;
                continue;
            }
            if bytes == b"--no-filename" {
                filename_mode = FilenameMode::Without;
                continue;
            }
            if bytes == b"--recursive" {
                recursive = true;
                continue;
            }
            if bytes.starts_with(b"--") {
                // Unsupported long option
                let mut err = io::stderr();
                let _ = err.write_all(b"rust_grep: unsupported option: ");
                let _ = err.write_all(bytes);
                let _ = err.write_all(b"\nusage: rust_grep PATTERN [FILE...]\n");
                exit(2);
            }
            if bytes.starts_with(b"-") && bytes.len() > 1 {
                // Short option cluster: each byte after '-' must be a known short option
                for c in &bytes[1..] {
                    if *c == b'H' {
                        filename_mode = FilenameMode::With;
                    } else if *c == b'h' {
                        filename_mode = FilenameMode::Without;
                    } else if *c == b'r' {
                        recursive = true;
                    } else {
                        let mut err = io::stderr();
                        let _ = err.write_all(b"rust_grep: unsupported option: ");
                        let _ = err.write_all(bytes);
                        let _ = err.write_all(b"\nusage: rust_grep PATTERN [FILE...]\n");
                        exit(2);
                    }
                }
                continue;
            }
            // bytes == b"-" or doesn't start with '-': it's an operand
        }
        if pattern.is_none() {
            pattern = Some(bytes.to_vec());
        } else {
            files.push(arg.clone());
        }
    }

    let pattern = match pattern {
        None => {
            let mut err = io::stderr();
            let _ = err.write_all(b"usage: rust_grep PATTERN [FILE...]\n");
            exit(2);
        }
        Some(p) => p,
    };

    let mut any_match = false;
    let mut any_error = false;

    if files.is_empty() {
        let mut input = Vec::new();
        if io::stdin().read_to_end(&mut input).is_err() {
            any_error = true;
        } else {
            let stdout = io::stdout();
            let mut out = stdout.lock();
            let stdin_prefix = if filename_mode == FilenameMode::With {
                Some(b"(standard input)" as &[u8])
            } else {
                None
            };
            match search_stream(&input, &pattern, stdin_prefix, &mut out) {
                Ok(m) => any_match = m,
                Err(_) => any_error = true,
            }
            let _ = out.flush();
        }
    } else {
        let any_dir_operand = files.iter().any(|f| Path::new(f).is_dir());
        let use_prefix = match filename_mode {
            FilenameMode::Without => false,
            FilenameMode::With => true,
            FilenameMode::Default => files.len() >= 2 || any_dir_operand,
        };

        let stdout = io::stdout();
        let mut out = stdout.lock();

        for file in &files {
            let path = Path::new(file);

            if path.is_dir() {
                if recursive {
                    let (m, e) = traverse_dir(file.as_os_str(), &pattern, use_prefix, &mut out);
                    any_match = any_match || m;
                    any_error = any_error || e;
                } else {
                    let mut err = io::stderr();
                    let _ = err.write_all(b"rust_grep: ");
                    let _ = err.write_all(file.as_bytes());
                    let _ = err.write_all(b": Is a directory\n");
                    any_error = true;
                }
                continue;
            }

            let prefix: Option<Vec<u8>> = if use_prefix {
                Some(file.as_bytes().to_vec())
            } else {
                None
            };
            let (m, e) = search_file_path(
                path,
                &pattern,
                prefix.as_deref(),
                &mut out,
            );
            any_match = any_match || m;
            any_error = any_error || e;
        }

        let _ = out.flush();
    }

    if any_error {
        exit(2);
    } else if any_match {
        exit(0);
    } else {
        exit(1);
    }
}
