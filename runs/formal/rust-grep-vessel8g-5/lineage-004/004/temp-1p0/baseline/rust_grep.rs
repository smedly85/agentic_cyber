use std::ffi::OsString;
use std::io::{self, Read, Write};
use std::os::unix::ffi::{OsStrExt, OsStringExt};

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

fn join_path(base: &OsString, component: &OsString) -> OsString {
    let base_bytes: &[u8] = base.as_bytes();
    let comp_bytes: &[u8] = component.as_bytes();
    let mut result = Vec::with_capacity(base_bytes.len() + 1 + comp_bytes.len());
    if base_bytes.last() == Some(&b'/') {
        result.extend_from_slice(base_bytes);
    } else {
        result.extend_from_slice(base_bytes);
        result.push(b'/');
    }
    result.extend_from_slice(comp_bytes);
    OsString::from_vec(result)
}

fn diagnose(display_path: &OsString, msg: &str) {
    let mut buf = display_path.as_bytes().to_vec();
    buf.push(b':');
    buf.push(b' ');
    buf.extend_from_slice(msg.as_bytes());
    buf.push(b'\n');
    eprint_bytes(&buf);
}

fn traverse_dir<W: Write>(
    dir_path: &OsString,
    display_base: &OsString,
    pattern: &[u8],
    writer: &mut W,
    need_prefix: bool,
) -> (bool, bool) {
    let mut any_match = false;
    let mut had_error = false;

    let read_dir = match std::fs::read_dir(dir_path) {
        Ok(rd) => rd,
        Err(e) => {
            diagnose(display_base, &e.to_string());
            return (false, true);
        }
    };

    let mut names: Vec<OsString> = Vec::new();
    for entry in read_dir {
        match entry {
            Ok(e) => names.push(e.file_name()),
            Err(e) => {
                had_error = true;
                diagnose(display_base, &e.to_string());
            }
        }
    }

    names.sort();

    for name in names {
        let child_path = join_path(dir_path, &name);
        let child_display = join_path(display_base, &name);

        let ft = match std::fs::symlink_metadata(&child_path) {
            Ok(m) => m.file_type(),
            Err(e) => {
                had_error = true;
                diagnose(&child_display, &e.to_string());
                continue;
            }
        };

        if ft.is_symlink() {
            continue;
        }

        if ft.is_dir() {
            let (m, e) = traverse_dir(&child_path, &child_display, pattern, writer, need_prefix);
            any_match = any_match || m;
            had_error = had_error || e;
        } else if ft.is_file() {
            let prefix: Option<Vec<u8>> = if need_prefix {
                let mut p = child_display.as_bytes().to_vec();
                p.push(b':');
                Some(p)
            } else {
                None
            };

            let mut fh = match std::fs::File::open(&child_path) {
                Ok(f) => f,
                Err(e) => {
                    had_error = true;
                    diagnose(&child_display, &e.to_string());
                    continue;
                }
            };

            match search_stream(&mut fh, writer, pattern, prefix.as_deref()) {
                Ok(m) => any_match = any_match || m,
                Err(e) => {
                    had_error = true;
                    diagnose(&child_display, &e.to_string());
                }
            }
        }
    }

    (any_match, had_error)
}

fn main() {
    let args: Vec<OsString> = std::env::args_os().skip(1).collect();

    let mut pattern: Option<Vec<u8>> = None;
    let mut files: Vec<OsString> = Vec::new();
    let mut seen_ddash = false;
    let mut filename_override: Option<bool> = None;
    let mut recursive = false;

    let usage = b"usage: rust_grep [-H] [-h] [-r] PATTERN [FILE...]";

    for arg in &args {
        let bytes: &[u8] = arg.as_bytes();
        if !seen_ddash {
            if bytes == b"--" {
                seen_ddash = true;
                continue;
            }
            if bytes.len() >= 2 && bytes[0] == b'-' && bytes[1] == b'-' {
                if bytes == b"--with-filename" {
                    filename_override = Some(true);
                } else if bytes == b"--no-filename" {
                    filename_override = Some(false);
                } else if bytes == b"--recursive" {
                    recursive = true;
                } else {
                    eprint_bytes(b"rust_grep: unsupported option");
                    eprint_bytes(usage);
                    std::process::exit(2);
                }
                continue;
            }
            if bytes.len() >= 2 && bytes[0] == b'-' {
                for &c in &bytes[1..] {
                    if c == b'H' {
                        filename_override = Some(true);
                    } else if c == b'h' {
                        filename_override = Some(false);
                    } else if c == b'r' {
                        recursive = true;
                    } else {
                        eprint_bytes(b"rust_grep: unsupported option");
                        eprint_bytes(usage);
                        std::process::exit(2);
                    }
                }
                continue;
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
            eprint_bytes(usage);
            std::process::exit(2);
        }
    };

    let stdout = io::stdout();
    let mut out = stdout.lock();
    let mut any_match = false;
    let mut had_error = false;

    let has_directory = files.iter().any(|f| {
        std::fs::metadata(f).map(|m| m.is_dir()).unwrap_or(false)
    });

    let need_prefix = match filename_override {
        Some(true) => true,
        Some(false) => false,
        None => files.len() >= 2 || has_directory,
    };

    if files.is_empty() {
        let stdin = io::stdin();
        let mut input = stdin.lock();
        let prefix: Option<Vec<u8>> = if need_prefix {
            Some(b"(standard input):".to_vec())
        } else {
            None
        };
        match search_stream(&mut input, &mut out, &pattern, prefix.as_deref()) {
            Ok(m) => any_match = m,
            Err(_) => {
                had_error = true;
                eprint_bytes(b"rust_grep: read error on stdin");
            }
        }
    } else {
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
                    diagnose(file, &e.to_string());
                    continue;
                }
            };

            if metadata.is_dir() {
                if recursive {
                    let (m, e) = traverse_dir(file, file, &pattern, &mut out, need_prefix);
                    any_match = any_match || m;
                    had_error = had_error || e;
                } else {
                    had_error = true;
                    let mut msg = file_bytes.to_vec();
                    msg.extend_from_slice(b": Is a directory\n");
                    eprint_bytes(&msg);
                    continue;
                }
            } else {
                let mut file_handle = match std::fs::File::open(file) {
                    Ok(f) => f,
                    Err(e) => {
                        had_error = true;
                        diagnose(file, &e.to_string());
                        continue;
                    }
                };

                match search_stream(&mut file_handle, &mut out, &pattern, prefix.as_deref()) {
                    Ok(m) => any_match = any_match || m,
                    Err(e) => {
                        had_error = true;
                        diagnose(file, &e.to_string());
                    }
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
