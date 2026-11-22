use std::env;
use std::ffi::OsString;
use std::fs::File;
use std::io::{self, BufRead, BufReader, Write};
use std::os::unix::ffi::OsStrExt;
use std::process;

#[derive(PartialEq)]
enum FilenameMode {
    Default,
    ForceOn,
    ForceOff,
}

fn case_fold(b: u8) -> u8 {
    if b >= b'A' && b <= b'Z' {
        b + 0x20
    } else {
        b
    }
}

fn contains_subslice(haystack: &[u8], needle: &[u8], case_insensitive: bool) -> bool {
    if needle.is_empty() {
        return true;
    }
    if needle.len() > haystack.len() {
        return false;
    }
    if case_insensitive {
        haystack.windows(needle.len()).any(|w| {
            w.iter().zip(needle.iter()).all(|(a, b)| case_fold(*a) == case_fold(*b))
        })
    } else {
        haystack.windows(needle.len()).any(|w| w == needle)
    }
}

fn search_stream<R: BufRead, W: Write>(
    reader: &mut R,
    writer: &mut W,
    pattern: &[u8],
    prefix: &[u8],
    case_insensitive: bool,
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
        if contains_subslice(content, pattern, case_insensitive) {
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

fn search_one_file(pattern: &[u8], path: &OsString, prefix: &[u8], case_insensitive: bool) -> io::Result<bool> {
    let file = File::open(path)?;
    let mut reader = BufReader::new(file);
    let stdout = io::stdout();
    let mut writer = stdout.lock();
    search_stream(&mut reader, &mut writer, pattern, prefix, case_insensitive)
}

fn join_path(base: &OsString, name: &OsString) -> OsString {
    let base_bytes = base.as_bytes();
    let mut result = OsString::new();
    result.push(base);
    if !base_bytes.is_empty() && base_bytes[base_bytes.len() - 1] != b'/' {
        result.push("/");
    }
    result.push(name);
    result
}

fn traverse_directory(
    pattern: &[u8],
    dir_path: &OsString,
    need_prefix: bool,
    any_match: &mut bool,
    any_error: &mut bool,
    case_insensitive: bool,
) {
    let entries = match std::fs::read_dir(dir_path) {
        Ok(entries) => entries,
        Err(e) => {
            let name = dir_path.to_string_lossy();
            let _ = writeln!(io::stderr(), "rust_grep: {}: {}", name, e);
            *any_error = true;
            return;
        }
    };

    let mut names: Vec<OsString> = Vec::new();
    for entry in entries {
        match entry {
            Ok(e) => names.push(e.file_name()),
            Err(e) => {
                let name = dir_path.to_string_lossy();
                let _ = writeln!(io::stderr(), "rust_grep: {}: {}", name, e);
                *any_error = true;
            }
        }
    }
    names.sort();

    for name in names {
        let full_path = join_path(dir_path, &name);

        let metadata = match std::fs::symlink_metadata(&full_path) {
            Ok(m) => m,
            Err(e) => {
                let display = full_path.to_string_lossy();
                let _ = writeln!(io::stderr(), "rust_grep: {}: {}", display, e);
                *any_error = true;
                continue;
            }
        };

        let file_type = metadata.file_type();

        if file_type.is_symlink() {
            continue;
        }

        if file_type.is_file() {
            let prefix: Vec<u8> = if need_prefix {
                let mut p = full_path.as_bytes().to_vec();
                p.push(b':');
                p
            } else {
                Vec::new()
            };
            match search_one_file(pattern, &full_path, &prefix, case_insensitive) {
                Ok(m) => {
                    if m {
                        *any_match = true;
                    }
                }
                Err(e) => {
                    let display = full_path.to_string_lossy();
                    let _ = writeln!(io::stderr(), "rust_grep: {}: {}", display, e);
                    *any_error = true;
                }
            }
        } else if file_type.is_dir() {
            traverse_directory(pattern, &full_path, need_prefix, any_match, any_error, case_insensitive);
        }
    }
}

fn main() {
    let args: Vec<OsString> = env::args_os().skip(1).collect();

    let mut pattern: Option<Vec<u8>> = None;
    let mut files: Vec<OsString> = Vec::new();
    let mut past_ddash = false;
    let mut filename_mode = FilenameMode::Default;
    let mut recursive = false;
    let mut ignore_case = false;

    for arg in &args {
        let bytes = arg.as_bytes();
        if !past_ddash && bytes == b"--" {
            past_ddash = true;
            continue;
        }
        if !past_ddash && bytes.len() > 1 && bytes[0] == b'-' {
            if bytes == b"--with-filename" {
                filename_mode = FilenameMode::ForceOn;
                continue;
            }
            if bytes == b"--no-filename" {
                filename_mode = FilenameMode::ForceOff;
                continue;
            }
            if bytes == b"--recursive" {
                recursive = true;
                continue;
            }
            if bytes == b"--ignore-case" {
                ignore_case = true;
                continue;
            }
            if bytes.starts_with(b"--") {
                let _ = writeln!(io::stderr(), "rust_grep: unsupported option: {}", String::from_utf8_lossy(&bytes[2..]));
                let _ = writeln!(io::stderr(), "rust_grep: usage: rust_grep [-H|-h|-r] PATTERN [FILE...]");
                process::exit(2);
            }
            // Short option(s): bytes[1..] each must be a supported letter.
            for c in &bytes[1..] {
                match c {
                    b'H' => filename_mode = FilenameMode::ForceOn,
                    b'h' => filename_mode = FilenameMode::ForceOff,
                    b'r' => { recursive = true; }
                    b'i' => { ignore_case = true; }
                    _ => {
                        let _ = writeln!(io::stderr(), "rust_grep: unsupported option: -{}", std::str::from_utf8(&[*c]).unwrap_or("?"));
                        let _ = writeln!(io::stderr(), "rust_grep: usage: rust_grep [-H|-h|-r] PATTERN [FILE...]");
                        process::exit(2);
                    }
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
            let _ = writeln!(io::stderr(), "rust_grep: usage: rust_grep [-H|-h|-r] PATTERN [FILE...]");
            process::exit(2);
        }
    };

    let mut any_match = false;
    let mut any_error = false;

    if files.is_empty() {
        let stdin_prefix: &[u8] = if filename_mode == FilenameMode::ForceOn {
            b"(standard input):"
        } else {
            b""
        };
        let stdin = io::stdin();
        let mut reader = BufReader::new(stdin.lock());
        let stdout = io::stdout();
        let mut writer = stdout.lock();
        match search_stream(&mut reader, &mut writer, &pattern, stdin_prefix, ignore_case) {
            Ok(m) => {
                any_match = m;
            }
            Err(e) => {
                let _ = writeln!(io::stderr(), "rust_grep: stdin: {}", e);
                any_error = true;
            }
        }
    } else {
        let need_prefix: bool = match filename_mode {
            FilenameMode::ForceOn => true,
            FilenameMode::ForceOff => false,
            FilenameMode::Default => {
                if recursive {
                    if files.len() > 1 {
                        true
                    } else {
                        std::fs::metadata(&files[0])
                            .map(|m| m.is_dir())
                            .unwrap_or(false)
                    }
                } else {
                    files.len() >= 2
                }
            }
        };

        for file in &files {
            if recursive {
                let metadata = match std::fs::metadata(file) {
                    Ok(m) => m,
                    Err(e) => {
                        let name = file.to_string_lossy();
                        let _ = writeln!(io::stderr(), "rust_grep: {}: {}", name, e);
                        any_error = true;
                        continue;
                    }
                };
                if metadata.is_dir() {
                    traverse_directory(&pattern, file, need_prefix, &mut any_match, &mut any_error, ignore_case);
                } else {
                    let prefix: Vec<u8> = if need_prefix {
                        let mut p = file.as_bytes().to_vec();
                        p.push(b':');
                        p
                    } else {
                        Vec::new()
                    };
                    match search_one_file(&pattern, file, &prefix, ignore_case) {
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
            } else {
                let prefix: Vec<u8> = if need_prefix {
                    let mut p = file.as_bytes().to_vec();
                    p.push(b':');
                    p
                } else {
                    Vec::new()
                };
                match search_one_file(&pattern, file, &prefix, ignore_case) {
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
    }

    let _ = io::stdout().flush();

    let code = if any_error { 2 } else if any_match { 0 } else { 1 };
    process::exit(code);
}
