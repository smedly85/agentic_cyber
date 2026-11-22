use std::env;
use std::ffi::OsString;
use std::fs::File;
use std::io::{self, BufReader, BufWriter, Read, Write};
use std::os::unix::ffi::OsStrExt;
use std::process;

fn search_stream(
    pattern: &[u8],
    mut reader: impl Read,
    mut output: impl Write,
    prefix: Option<&[u8]>,
) -> io::Result<bool> {
    let mut line_buf: Vec<u8> = Vec::with_capacity(4096);
    let mut matched_any = false;
    let mut chunk = [0u8; 8192];

    loop {
        let n = reader.read(&mut chunk)?;
        if n == 0 {
            if !line_buf.is_empty() {
                if pattern.is_empty()
                    || line_buf.windows(pattern.len()).any(|w| w == pattern)
                {
                    if let Some(p) = prefix {
                        output.write_all(p)?;
                    }
                    output.write_all(&line_buf)?;
                    output.write_all(b"\n")?;
                    matched_any = true;
                }
            }
            break;
        }
        for &byte in &chunk[..n] {
            if byte == 0x0A {
                if pattern.is_empty()
                    || line_buf.windows(pattern.len()).any(|w| w == pattern)
                {
                    if let Some(p) = prefix {
                        output.write_all(p)?;
                    }
                    output.write_all(&line_buf)?;
                    output.write_all(b"\n")?;
                    matched_any = true;
                }
                line_buf.clear();
            } else {
                line_buf.push(byte);
            }
        }
    }
    Ok(matched_any)
}

fn main() {
    let args: Vec<OsString> = env::args_os().skip(1).collect();

    let mut pattern: Option<OsString> = None;
    let mut files: Vec<OsString> = Vec::new();
    let mut end_of_options = false;
    let mut filename_policy: Option<bool> = None; // None=default, Some(true)=with, Some(false)=without

    fn usage_err() -> ! {
        eprintln!("rust_grep: unsupported option");
        eprintln!("usage: rust_grep [OPTION] PATTERN [FILE...]");
        process::exit(2);
    }

    for arg in &args {
        let bytes = arg.as_bytes();

        if end_of_options {
            if pattern.is_none() {
                pattern = Some(arg.clone());
            } else {
                files.push(arg.clone());
            }
            continue;
        }

        if bytes == b"--" {
            end_of_options = true;
            continue;
        }

        if bytes == b"-" {
            if pattern.is_none() {
                pattern = Some(arg.clone());
            } else {
                files.push(arg.clone());
            }
            continue;
        }

        if bytes.len() > 2 && bytes.starts_with(b"--") {
            if bytes == b"--with-filename" {
                filename_policy = Some(true);
            } else if bytes == b"--no-filename" {
                filename_policy = Some(false);
            } else {
                usage_err();
            }
            continue;
        }

        if bytes.len() > 1 && bytes[0] == b'-' {
            for &c in &bytes[1..] {
                if c == b'H' {
                    filename_policy = Some(true);
                } else if c == b'h' {
                    filename_policy = Some(false);
                } else {
                    usage_err();
                }
            }
            continue;
        }

        if pattern.is_none() {
            pattern = Some(arg.clone());
        } else {
            files.push(arg.clone());
        }
    }

    let pattern = match pattern {
        Some(p) => p,
        None => {
            eprintln!("rust_grep: missing PATTERN");
            eprintln!("usage: rust_grep [OPTION] PATTERN [FILE...]");
            process::exit(2);
        }
    };

    let pattern_bytes: Vec<u8> = pattern.as_bytes().to_vec();

    let mut any_match = false;
    let mut any_error = false;

    let stdout = io::stdout();
    let mut out = BufWriter::new(stdout.lock());

    if files.is_empty() {
        let stdin = io::stdin();
        let mut reader = BufReader::new(stdin.lock());
        let stdin_prefix: Option<Vec<u8>> = if filename_policy == Some(true) {
            Some(b"(standard input):"[..].to_vec())
        } else {
            None
        };
        match search_stream(&pattern_bytes, &mut reader, &mut out, stdin_prefix.as_deref()) {
            Ok(matched) => {
                any_match = matched;
            }
            Err(_) => {
                any_error = true;
            }
        }
    } else {
        let multi = files.len() >= 2;
        for file in &files {
            let display = file.to_string_lossy();
            let file_bytes: Vec<u8> = file.as_bytes().to_vec();

            let f = match File::open(file) {
                Ok(f) => f,
                Err(e) => {
                    eprintln!("rust_grep: {}: {}", display, e);
                    any_error = true;
                    continue;
                }
            };

            let meta = match f.metadata() {
                Ok(m) => m,
                Err(e) => {
                    eprintln!("rust_grep: {}: {}", display, e);
                    any_error = true;
                    continue;
                }
            };

            if meta.is_dir() {
                eprintln!("rust_grep: {}: Is a directory", display);
                any_error = true;
                continue;
            }

            let mut reader = BufReader::new(f);
            let prefix_bytes: Option<Vec<u8>> = match filename_policy {
                Some(true) => {
                    let mut p = file_bytes;
                    p.push(b':');
                    Some(p)
                }
                Some(false) => None,
                None if multi => {
                    let mut p = file_bytes;
                    p.push(b':');
                    Some(p)
                }
                None => None,
            };

            match search_stream(
                &pattern_bytes,
                &mut reader,
                &mut out,
                prefix_bytes.as_deref(),
            ) {
                Ok(matched) => {
                    if matched {
                        any_match = true;
                    }
                }
                Err(e) => {
                    eprintln!("rust_grep: {}: {}", display, e);
                    any_error = true;
                }
            }
        }
    }

    if out.flush().is_err() {
        any_error = true;
    }

    if any_error {
        process::exit(2);
    } else if any_match {
        process::exit(0);
    } else {
        process::exit(1);
    }
}
