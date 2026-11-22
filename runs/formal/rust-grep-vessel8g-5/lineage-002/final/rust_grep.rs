use std::env;
use std::ffi::{OsStr, OsString};
use std::fs;
use std::io::{self, Read, Write};
use std::os::unix::ffi::{OsStrExt, OsStringExt};
use std::path::Path;

fn fold_byte(b: u8) -> u8 {
    if (0x41..=0x5A).contains(&b) { b + 0x20 } else { b }
}

fn bytes_ci_equal(a: &[u8], b: &[u8], ci: bool) -> bool {
    if a.len() != b.len() {
        return false;
    }
    if !ci {
        return a == b;
    }
    for (&x, &y) in a.iter().zip(b.iter()) {
        let fx = if (0x41..=0x5A).contains(&x) { x + 0x20 } else { x };
        let fy = if (0x41..=0x5A).contains(&y) { y + 0x20 } else { y };
        if fx != fy {
            return false;
        }
    }
    true
}

fn line_contains_pattern(line: &[u8], pattern: &[u8], ci: bool) -> bool {
    if pattern.is_empty() {
        return true;
    }
    if line.len() < pattern.len() {
        return false;
    }
    if !ci {
        return line
            .windows(pattern.len())
            .any(|w| w == pattern);
    }
    let folded_pattern: Vec<u8> = pattern.iter().map(|&b| fold_byte(b)).collect();
    let plen = folded_pattern.len();
    let max_start = line.len() - plen;
    for i in 0..=max_start {
        let window = &line[i..i + plen];
        if bytes_ci_equal(window, pattern, ci) {
            return true;
        }
        // Optimization: also try comparing against folded pattern directly
        let mut ok = true;
        for j in 0..plen {
            if fold_byte(window[j]) != folded_pattern[j] {
                ok = false;
                break;
            }
        }
        if ok {
            return true;
        }
    }
    false
}

fn emit_line(out: &mut dyn Write, prefix: Option<&[u8]>, line: &[u8]) -> io::Result<()> {
    if let Some(p) = prefix {
        out.write_all(p)?;
        out.write_all(b":")?;
    }
    out.write_all(line)?;
    out.write_all(b"\n")?;
    Ok(())
}

fn search_stream<R: Read>(
    reader: &mut R,
    pattern: &[u8],
    ci: bool,
    prefix: Option<&[u8]>,
    out: &mut dyn Write,
) -> io::Result<bool> {
    let mut buf = vec![0u8; 65536];
    let mut line = Vec::new();
    let mut found = false;

    loop {
        let n = match reader.read(&mut buf) {
            Ok(0) => {
                if !line.is_empty() {
                    if line_contains_pattern(&line, pattern, ci) {
                        emit_line(out, prefix, &line)?;
                        found = true;
                    }
                }
                break;
            }
            Ok(n) => n,
            Err(ref e) if e.kind() == io::ErrorKind::Interrupted => continue,
            Err(e) => return Err(e),
        };

        let data = &buf[..n];
        let mut start = 0usize;
        while start < data.len() {
            match data[start..].iter().position(|&b| b == 0x0A) {
                Some(pos) => {
                    let end = start + pos;
                    line.extend_from_slice(&data[start..end]);
                    if line_contains_pattern(&line, pattern, ci) {
                        emit_line(out, prefix, &line)?;
                        found = true;
                    }
                    line.clear();
                    start = end + 1;
                }
                None => {
                    line.extend_from_slice(&data[start..]);
                    break;
                }
            }
        }
    }
    Ok(found)
}

fn join_os(parent: &OsStr, child: &OsStr) -> OsString {
    let p = parent.as_bytes();
    let c = child.as_bytes();
    let mut result = Vec::with_capacity(p.len() + 1 + c.len());
    result.extend_from_slice(p);
    if !p.is_empty() && *p.last().unwrap() != b'/' {
        result.push(b'/');
    }
    result.extend_from_slice(c);
    OsString::from_vec(result)
}

fn display_os(s: &OsStr) -> String {
    String::from_utf8_lossy(s.as_bytes()).into_owned()
}

fn normalize_operand(path: &OsStr) -> OsString {
    let bytes = path.as_bytes();
    let mut end = bytes.len();
    while end > 1 && bytes[end - 1] == b'/' {
        end -= 1;
    }
    OsString::from_vec(bytes[..end].to_vec())
}

fn recursive_traverse(
    dir: &OsStr,
    pattern: &[u8],
    ci: bool,
    use_prefix: bool,
    out: &mut dyn Write,
    found: &mut bool,
    had_error: &mut bool,
) {
    let entries = match fs::read_dir(dir) {
        Ok(e) => e,
        Err(e) => {
            eprintln!("rust_grep: {}: {}", display_os(dir), e);
            *had_error = true;
            return;
        }
    };

    let mut names: Vec<OsString> = Vec::new();
    for entry in entries {
        match entry {
            Ok(e) => names.push(e.file_name()),
            Err(e) => {
                eprintln!("rust_grep: {}: {}", display_os(dir), e);
                *had_error = true;
            }
        }
    }
    names.sort();

    for name in &names {
        let full = join_os(dir, name);
        let meta = match fs::symlink_metadata(&full) {
            Ok(m) => m,
            Err(e) => {
                eprintln!("rust_grep: {}: {}", display_os(&full), e);
                *had_error = true;
                continue;
            }
        };

        if meta.file_type().is_symlink() {
            continue;
        }

        if meta.is_dir() {
            recursive_traverse(&full, pattern, ci, use_prefix, out, found, had_error);
        } else if meta.is_file() {
            let mut file = match fs::File::open(&full) {
                Ok(f) => f,
                Err(e) => {
                    eprintln!("rust_grep: {}: {}", display_os(&full), e);
                    *had_error = true;
                    continue;
                }
            };
            let prefix: Option<Vec<u8>> = if use_prefix {
                Some(full.as_bytes().to_vec())
            } else {
                None
            };
            match search_stream(&mut file, pattern, ci, prefix.as_deref(), out) {
                Ok(f) => {
                    *found = *found || f;
                }
                Err(e) => {
                    eprintln!("rust_grep: {}: {}", display_os(&full), e);
                    *had_error = true;
                }
            }
        }
    }
}

#[derive(Clone, Copy)]
enum FilenameMode {
    Default,
    With,
    Without,
}

fn main() {
    let args: Vec<OsString> = env::args_os().collect();

    let mut pattern: Option<Vec<u8>> = None;
    let mut files: Vec<OsString> = Vec::new();
    let mut filename_mode = FilenameMode::Default;
    let mut recursive = false;
    let mut ignore_case = false;
    let mut after_ddash = false;

    for arg in &args[1..] {
        let bytes = arg.as_bytes();

        if after_ddash {
            if pattern.is_none() {
                pattern = Some(bytes.to_vec());
            } else {
                files.push(arg.clone());
            }
            continue;
        }

        if bytes == b"--" {
            after_ddash = true;
            continue;
        }

        if bytes.len() > 2 && bytes[0] == b'-' && bytes[1] == b'-' {
            let opt_name = &bytes[2..];
            let opt_str = String::from_utf8_lossy(opt_name);
            match opt_str.as_ref() {
                "with-filename" => filename_mode = FilenameMode::With,
                "no-filename" => filename_mode = FilenameMode::Without,
                "recursive" => recursive = true,
                "ignore-case" => ignore_case = true,
                _ => {
                    eprintln!("rust_grep: unsupported option '--{}'", opt_str);
                    std::process::exit(2);
                }
            }
            continue;
        }

        if bytes.len() >= 2 && bytes[0] == b'-' && bytes[1] != b'-' {
            for &c in &bytes[1..] {
                match c {
                    b'H' => filename_mode = FilenameMode::With,
                    b'h' => filename_mode = FilenameMode::Without,
                    b'r' => recursive = true,
                    b'i' => ignore_case = true,
                    _ => {
                        eprintln!(
                            "rust_grep: unsupported option '-{}'",
                            (c as char)
                        );
                        std::process::exit(2);
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
            eprintln!("rust_grep: missing PATTERN");
            std::process::exit(2);
        }
    };

    let mut out = io::stdout();
    let mut found_any = false;
    let mut had_error = false;

    if files.is_empty() {
        let prefix: Option<Vec<u8>> = match filename_mode {
            FilenameMode::With => Some(b"(standard input)".to_vec()),
            _ => None,
        };
        let stdin = io::stdin();
        let mut stdin_lock = stdin.lock();
        match search_stream(
            &mut stdin_lock,
            &pattern,
            ignore_case,
            prefix.as_deref(),
            &mut out,
        ) {
            Ok(f) => found_any = f,
            Err(_) => had_error = true,
        }
    } else {
        let use_prefix = match filename_mode {
            FilenameMode::With => true,
            FilenameMode::Without => false,
            FilenameMode::Default => {
                if files.len() >= 2 {
                    true
                } else {
                    files.iter().any(|f| Path::new(f).is_dir())
                }
            }
        };

        for file in &files {
            let path = Path::new(file);

            let file_meta = match fs::symlink_metadata(path) {
                Ok(m) => m,
                Err(_) => {
                    eprintln!(
                        "rust_grep: {}: No such file or directory",
                        display_os(file)
                    );
                    had_error = true;
                    continue;
                }
            };

            if file_meta.is_dir() {
                if !recursive {
                    eprintln!("rust_grep: {}: Is a directory", display_os(file));
                    had_error = true;
                    continue;
                }
                let normalized = normalize_operand(file);
                recursive_traverse(
                    &normalized,
                    &pattern,
                    ignore_case,
                    use_prefix,
                    &mut out,
                    &mut found_any,
                    &mut had_error,
                );
                continue;
            }

            if file_meta.file_type().is_symlink() {
                let target_meta = match fs::metadata(path) {
                    Ok(m) => m,
                    Err(_) => {
                        eprintln!(
                            "rust_grep: {}: No such file or directory",
                            display_os(file)
                        );
                        had_error = true;
                        continue;
                    }
                };
                if target_meta.is_dir() {
                    if !recursive {
                        eprintln!(
                            "rust_grep: {}: Is a directory",
                            display_os(file)
                        );
                        had_error = true;
                        continue;
                    }
                    let normalized = normalize_operand(file);
                    recursive_traverse(
                        &normalized,
                        &pattern,
                        ignore_case,
                        use_prefix,
                        &mut out,
                        &mut found_any,
                        &mut had_error,
                    );
                    continue;
                }
            }

            let mut file_handle = match fs::File::open(path) {
                Ok(f) => f,
                Err(e) => {
                    eprintln!("rust_grep: {}: {}", display_os(file), e);
                    had_error = true;
                    continue;
                }
            };
            let prefix: Option<Vec<u8>> = if use_prefix {
                Some(file.as_bytes().to_vec())
            } else {
                None
            };
            match search_stream(
                &mut file_handle,
                &pattern,
                ignore_case,
                prefix.as_deref(),
                &mut out,
            ) {
                Ok(f) => found_any = found_any || f,
                Err(e) => {
                    eprintln!("rust_grep: {}: {}", display_os(file), e);
                    had_error = true;
                }
            }
        }
    }

    let exit_code = if had_error {
        2
    } else if found_any {
        0
    } else {
        1
    };
    std::process::exit(exit_code);
}
