use std::env;
use std::ffi::OsString;
use std::fs::File;
use std::io::{self, Read, Write};
use std::os::unix::ffi::OsStrExt;
use std::path::Path;
use std::process::exit;

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

fn main() {
    let args_os: Vec<OsString> = env::args_os().collect();
    let args: &[OsString] = if args_os.len() > 1 { &args_os[1..] } else { &[] };

    let mut pattern: Option<Vec<u8>> = None;
    let mut files: Vec<OsString> = Vec::new();
    let mut after_ddash = false;
    let mut with_filename = false;

    for arg in args {
        let bytes: &[u8] = arg.as_bytes();
        if !after_ddash {
            if bytes == b"--" {
                after_ddash = true;
                continue;
            }
            if bytes == b"--with-filename" {
                with_filename = true;
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
                        with_filename = true;
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
            let stdin_prefix = if with_filename {
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
        for file in &files {
            let path = Path::new(file);
            if path.is_dir() {
                let mut err = io::stderr();
                let _ = err.write_all(b"rust_grep: ");
                let _ = err.write_all(file.as_bytes());
                let _ = err.write_all(b": Is a directory\n");
                any_error = true;
                continue;
            }
            let mut opened = match File::open(path) {
                Ok(f) => f,
                Err(_) => {
                    let mut err = io::stderr();
                    let _ = err.write_all(b"rust_grep: ");
                    let _ = err.write_all(file.as_bytes());
                    let _ = err.write_all(b": cannot open\n");
                    any_error = true;
                    continue;
                }
            };
            let mut input = Vec::new();
            if let Err(_) = opened.read_to_end(&mut input) {
                let mut err = io::stderr();
                let _ = err.write_all(b"rust_grep: ");
                let _ = err.write_all(file.as_bytes());
                let _ = err.write_all(b": read error\n");
                any_error = true;
                continue;
            }
            let prefix = if with_filename || files.len() >= 2 {
                Some(file.as_bytes())
            } else {
                None
            };
            let stdout = io::stdout();
            let mut out = stdout.lock();
            match search_stream(&input, &pattern, prefix, &mut out) {
                Ok(m) => any_match = any_match || m,
                Err(_) => any_error = true,
            }
            let _ = out.flush();
        }
    }

    let _ = io::stdout().flush();
    if any_error {
        exit(2);
    } else if any_match {
        exit(0);
    } else {
        exit(1);
    }
}
