use std::env;
use std::ffi::OsString;
use std::fs::File;
use std::io::{self, BufRead, BufReader, Write};
use std::os::unix::ffi::OsStrExt;
use std::process;

fn contains_subslice(haystack: &[u8], needle: &[u8]) -> bool {
    if needle.is_empty() {
        return true;
    }
    if needle.len() > haystack.len() {
        return false;
    }
    haystack.windows(needle.len()).any(|w| w == needle)
}

fn search_stream<R: BufRead, W: Write>(
    reader: &mut R,
    writer: &mut W,
    pattern: &[u8],
    prefix: &[u8],
) -> io::Result<bool> {
    let mut matched = false;
    let mut line = Vec::new();
    loop {
        line.clear();
        let n = reader.read_until(b'\n', &mut line)?;
        if n == 0 {
            break;
        }
        let content = if line.last() == Some(&b'\n') {
            &line[..line.len() - 1]
        } else {
            &line[..]
        };
        if contains_subslice(content, pattern) {
            if !prefix.is_empty() {
                writer.write_all(prefix)?;
            }
            writer.write_all(content)?;
            writer.write_all(b"\n")?;
            matched = true;
        }
    }
    Ok(matched)
}

fn search_one_file(pattern: &[u8], path: &OsString, prefix: &[u8]) -> io::Result<bool> {
    let file = File::open(path)?;
    let mut reader = BufReader::new(file);
    let stdout = io::stdout();
    let mut writer = stdout.lock();
    search_stream(&mut reader, &mut writer, pattern, prefix)
}

fn main() {
    let args: Vec<OsString> = env::args_os().skip(1).collect();

    let mut pattern: Option<Vec<u8>> = None;
    let mut files: Vec<OsString> = Vec::new();
    let mut past_ddash = false;
    let mut with_filename = false;

    for arg in &args {
        let bytes = arg.as_bytes();
        if !past_ddash && bytes == b"--" {
            past_ddash = true;
            continue;
        }
        if !past_ddash && bytes.len() > 1 && bytes[0] == b'-' {
            if bytes == b"--with-filename" {
                with_filename = true;
                continue;
            }
            if bytes.starts_with(b"--") {
                let _ = writeln!(io::stderr(), "rust_grep: unsupported option: {}", String::from_utf8_lossy(&bytes[2..]));
                let _ = writeln!(io::stderr(), "rust_grep: usage: rust_grep [-H] PATTERN [FILE...]");
                process::exit(2);
            }
            // Short option(s): bytes[1..] each must be a supported letter.
            for c in &bytes[1..] {
                if *c == b'H' {
                    with_filename = true;
                } else {
                    let _ = writeln!(io::stderr(), "rust_grep: unsupported option: -{}", std::str::from_utf8(&[*c]).unwrap_or("?"));
                    let _ = writeln!(io::stderr(), "rust_grep: usage: rust_grep [-H] PATTERN [FILE...]");
                    process::exit(2);
                }
            }
            continue;
        }
        if pattern.is_none() {
            pattern = Some(bytes.to_vec());
        } else {
            files.push(arg.clone());
        }
    }

    let pattern = match pattern {
        Some(p) => p,
        None => {
            let _ = writeln!(io::stderr(), "rust_grep: usage: rust_grep [-H] PATTERN [FILE...]");
            process::exit(2);
        }
    };

    let mut any_match = false;
    let mut any_error = false;

    if files.is_empty() {
        let stdin_prefix: &[u8] = if with_filename {
            b"(standard input):"
        } else {
            b""
        };
        let stdin = io::stdin();
        let mut reader = BufReader::new(stdin.lock());
        let stdout = io::stdout();
        let mut writer = stdout.lock();
        match search_stream(&mut reader, &mut writer, &pattern, stdin_prefix) {
            Ok(m) => {
                any_match = m;
            }
            Err(e) => {
                let _ = writeln!(io::stderr(), "rust_grep: stdin: {}", e);
                any_error = true;
            }
        }
    } else {
        let need_prefix = with_filename || files.len() >= 2;
        for file in &files {
            let prefix: Vec<u8> = if need_prefix {
                let mut p = file.as_bytes().to_vec();
                p.push(b':');
                p
            } else {
                Vec::new()
            };

            match search_one_file(&pattern, file, &prefix) {
                Ok(m) => {
                    if m {
                        any_match = true;
                    }
                }
                Err(e) => {
                    let name = file.to_string_lossy();
                    let _ = writeln!(io::stderr(), "rust_grep: {}: {}", name, e);
                    any_error = true;
                }
            }
        }
    }

    let _ = io::stdout().flush();

    let code = if any_error { 2 } else if any_match { 0 } else { 1 };
    process::exit(code);
}
