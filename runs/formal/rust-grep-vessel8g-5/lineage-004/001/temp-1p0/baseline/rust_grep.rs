use std::ffi::OsString;
use std::io::{self, Read, Write};
use std::os::unix::ffi::OsStrExt;

fn search_stream<R: Read, W: Write>(
    reader: &mut R,
    writer: &mut W,
    pattern: &[u8],
    prefix: Option<&[u8]>,
) -> io::Result<bool> {
    let mut buf = [0u8; 8192];
    let mut line: Vec<u8> = Vec::new();
    let mut any_match = false;

    loop {
        let n = reader.read(&mut buf)?;
        if n == 0 {
            if !line.is_empty() {
                if line_contains(&line, pattern) {
                    emit_line(writer, &line, prefix)?;
                    any_match = true;
                }
            }
            return Ok(any_match);
        }
        for &byte in &buf[..n] {
            if byte == b'\n' {
                if line_contains(&line, pattern) {
                    emit_line(writer, &line, prefix)?;
                    any_match = true;
                }
                line.clear();
            } else {
                line.push(byte);
            }
        }
    }
}

fn line_contains(line: &[u8], pattern: &[u8]) -> bool {
    if pattern.is_empty() {
        return true;
    }
    if pattern.len() > line.len() {
        return false;
    }
    line.windows(pattern.len()).any(|w| w == pattern)
}

fn emit_line<W: Write>(writer: &mut W, line: &[u8], prefix: Option<&[u8]>) -> io::Result<()> {
    if let Some(p) = prefix {
        writer.write_all(p)?;
    }
    writer.write_all(line)?;
    writer.write_all(b"\n")?;
    Ok(())
}

fn eprint_bytes(bytes: &[u8]) {
    let stderr = io::stderr();
    let mut h = stderr.lock();
    let _ = h.write_all(bytes);
    let _ = h.write_all(b"\n");
}

fn main() {
    let args: Vec<OsString> = std::env::args_os().skip(1).collect();

    let mut pattern: Option<Vec<u8>> = None;
    let mut files: Vec<OsString> = Vec::new();
    let mut seen_ddash = false;

    for arg in &args {
        let bytes: &[u8] = arg.as_bytes();
        if !seen_ddash {
            if bytes == b"--" {
                seen_ddash = true;
                continue;
            }
            if bytes.len() > 1 && bytes[0] == b'-' {
                eprint_bytes(b"rust_grep: unsupported option");
                eprint_bytes(b"usage: rust_grep PATTERN [FILE...]");
                std::process::exit(2);
            }
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
            eprint_bytes(b"rust_grep: missing PATTERN");
            eprint_bytes(b"usage: rust_grep PATTERN [FILE...]");
            std::process::exit(2);
        }
    };

    let stdout = io::stdout();
    let mut out = stdout.lock();
    let mut any_match = false;
    let mut had_error = false;

    if files.is_empty() {
        let stdin = io::stdin();
        let mut input = stdin.lock();
        match search_stream(&mut input, &mut out, &pattern, None) {
            Ok(m) => any_match = m,
            Err(_) => {
                had_error = true;
                eprint_bytes(b"rust_grep: read error on stdin");
            }
        }
    } else {
        let need_prefix = files.len() >= 2;
        for file in &files {
            let file_bytes: &[u8] = file.as_bytes();
            let prefix: Option<Vec<u8>> = if need_prefix {
                let mut p = file_bytes.to_vec();
                p.push(b':');
                Some(p)
            } else {
                None
            };

            let metadata = match std::fs::metadata(file) {
                Ok(m) => m,
                Err(e) => {
                    had_error = true;
                    let mut msg = file_bytes.to_vec();
                    msg.push(b':');
                    msg.push(b' ');
                    msg.extend_from_slice(e.to_string().as_bytes());
                    msg.push(b'\n');
                    eprint_bytes(&msg);
                    continue;
                }
            };

            if metadata.is_dir() {
                had_error = true;
                let mut msg = file_bytes.to_vec();
                msg.extend_from_slice(b": Is a directory\n");
                eprint_bytes(&msg);
                continue;
            }

            let mut file_handle = match std::fs::File::open(file) {
                Ok(f) => f,
                Err(e) => {
                    had_error = true;
                    let mut msg = file_bytes.to_vec();
                    msg.push(b':');
                    msg.push(b' ');
                    msg.extend_from_slice(e.to_string().as_bytes());
                    msg.push(b'\n');
                    eprint_bytes(&msg);
                    continue;
                }
            };

            match search_stream(&mut file_handle, &mut out, &pattern, prefix.as_deref()) {
                Ok(m) => any_match = any_match || m,
                Err(e) => {
                    had_error = true;
                    let mut msg = file_bytes.to_vec();
                    msg.push(b':');
                    msg.push(b' ');
                    msg.extend_from_slice(e.to_string().as_bytes());
                    msg.push(b'\n');
                    eprint_bytes(&msg);
                }
            }
        }
    }

    let _ = out.flush();

    if had_error {
        std::process::exit(2);
    } else if any_match {
        std::process::exit(0);
    } else {
        std::process::exit(1);
    }
}
