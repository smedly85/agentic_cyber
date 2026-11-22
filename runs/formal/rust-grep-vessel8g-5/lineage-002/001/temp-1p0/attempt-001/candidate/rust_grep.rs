use std::env;
use std::ffi::OsString;
use std::fs::File;
use std::io::{self, BufReader, Read, Write};
use std::os::unix::ffi::OsStrExt;
use std::process;

fn contains_substring(haystack: &[u8], needle: &[u8]) -> bool {
    if needle.is_empty() {
        return true;
    }
    if needle.len() > haystack.len() {
        return false;
    }
    haystack.windows(needle.len()).any(|w| w == needle)
}

fn read_line(input: &mut dyn Read, buf: &mut Vec<u8>) -> io::Result<usize> {
    let mut byte_buf = [0u8; 1];
    loop {
        let n = input.read(&mut byte_buf)?;
        if n == 0 {
            return Ok(buf.len());
        }
        buf.push(byte_buf[0]);
        if byte_buf[0] == b'\n' {
            return Ok(buf.len());
        }
    }
}

fn search_stream(
    pattern: &[u8],
    input: &mut dyn Read,
    output: &mut dyn Write,
    prefix: Option<&[u8]>,
) -> io::Result<bool> {
    let mut any_selected = false;
    let mut line_buf: Vec<u8> = Vec::new();

    loop {
        line_buf.clear();
        let n = read_line(input, &mut line_buf)?;
        if n == 0 {
            break;
        }
        let content = if line_buf[n - 1] == b'\n' {
            &line_buf[..n - 1]
        } else {
            &line_buf[..n]
        };
        if contains_substring(content, pattern) {
            if let Some(p) = prefix {
                output.write_all(p)?;
            }
            output.write_all(content)?;
            output.write_all(b"\n")?;
            any_selected = true;
        }
    }

    Ok(any_selected)
}

fn usage_exit() -> ! {
    let _ = io::stderr().write_all(b"rust_grep: usage: rust_grep PATTERN [FILE...]\n");
    let _ = io::stderr().flush();
    process::exit(2);
}

fn file_diagnostic(path: &OsString, msg: &str) {
    let mut err = io::stderr();
    let _ = err.write_all(b"rust_grep: ");
    let _ = err.write_all(path.as_bytes());
    let _ = err.write_all(b": ");
    let _ = err.write_all(msg.as_bytes());
    let _ = err.write_all(b"\n");
    let _ = err.flush();
}

fn main() {
    let args: Vec<OsString> = env::args_os().collect();

    let mut pattern: Option<Vec<u8>> = None;
    let mut files: Vec<OsString> = Vec::new();
    let mut with_filename = false;
    let mut after_ddash = false;

    for arg in args.iter().skip(1) {
        if !after_ddash {
            let b = arg.as_bytes();
            if b == b"--" {
                after_ddash = true;
                continue;
            }
            if b == b"--with-filename" {
                with_filename = true;
                continue;
            }
            if b.len() > 1 && b[0] == b'-' {
                // short option cluster: every char after '-' must be 'H'
                if b[1..].iter().all(|&c| c == b'H') {
                    with_filename = true;
                    continue;
                }
                usage_exit();
            }
        }
        if pattern.is_none() {
            pattern = Some(arg.as_bytes().to_vec());
        } else {
            files.push(arg.clone());
        }
    }

    let pattern = match pattern {
        Some(p) => p,
        None => usage_exit(),
    };

    let stdout = io::stdout();
    let mut out = stdout.lock();
    let mut any_selected = false;
    let mut had_error = false;

    if files.is_empty() {
        let stdin = io::stdin();
        let mut reader = BufReader::new(stdin.lock());
        let stdin_prefix: Option<&[u8]> = if with_filename {
            Some(b"(standard input):")
        } else {
            None
        };
        match search_stream(&pattern, &mut reader, &mut out, stdin_prefix) {
            Ok(s) => any_selected = s,
            Err(_) => had_error = true,
        }
    } else {
        let need_prefix = files.len() >= 2 || with_filename;
        for path in &files {
            let file = match File::open(path) {
                Ok(f) => f,
                Err(_) => {
                    file_diagnostic(path, "cannot open");
                    had_error = true;
                    continue;
                }
            };
            let meta = match file.metadata() {
                Ok(m) => m,
                Err(_) => {
                    file_diagnostic(path, "cannot stat");
                    had_error = true;
                    continue;
                }
            };
            if meta.is_dir() {
                file_diagnostic(path, "is a directory");
                had_error = true;
                continue;
            }
            let mut reader = BufReader::new(file);
            let prefix = if need_prefix {
                let mut p = path.as_bytes().to_vec();
                p.push(b':');
                Some(p)
            } else {
                None
            };
            match search_stream(&pattern, &mut reader, &mut out, prefix.as_deref()) {
                Ok(s) => {
                    if s {
                        any_selected = true;
                    }
                }
                Err(_) => had_error = true,
            }
        }
    }

    let _ = out.flush();

    if had_error {
        process::exit(2);
    } else if any_selected {
        process::exit(0);
    } else {
        process::exit(1);
    }
}
