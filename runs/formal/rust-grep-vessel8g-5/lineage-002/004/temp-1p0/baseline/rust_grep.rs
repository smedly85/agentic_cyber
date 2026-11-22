use std::ffi::OsString;
use std::fs::{self, File};
use std::io::{self, BufReader, Read, Write};
use std::os::unix::ffi::OsStrExt;
use std::path::Path;
use std::process;

/// Core line-selection: read lines from `reader`, emit those containing `pattern`
/// to `out`, with optional prefix. Returns true if any line was selected.
fn search_stream(
    reader: &mut dyn Read,
    pattern: &[u8],
    out: &mut dyn Write,
    prefix: Option<&OsString>,
) -> io::Result<bool> {
    let mut found = false;
    let mut buf = [0u8; 8192];
    let mut line: Vec<u8> = Vec::new();

    loop {
        let n = reader.read(&mut buf)?;
        if n == 0 {
            if !line.is_empty() {
                if matches_line(&line, pattern) {
                    emit_line(out, prefix, &line)?;
                    found = true;
                }
                line.clear();
            }
            break;
        }
        for &b in &buf[..n] {
            if b == 0x0A {
                if matches_line(&line, pattern) {
                    emit_line(out, prefix, &line)?;
                    found = true;
                }
                line.clear();
            } else {
                line.push(b);
            }
        }
    }

    Ok(found)
}

fn matches_line(line: &[u8], pattern: &[u8]) -> bool {
    if pattern.is_empty() {
        return true;
    }
    if pattern.len() > line.len() {
        return false;
    }
    line.windows(pattern.len()).any(|w| w == pattern)
}

fn emit_line(out: &mut dyn Write, prefix: Option<&OsString>, line: &[u8]) -> io::Result<()> {
    if let Some(p) = prefix {
        out.write_all(p.as_bytes())?;
        out.write_all(b":")?;
    }
    out.write_all(line)?;
    out.write_all(b"\n")?;
    Ok(())
}

fn search_file(
    path: &OsString,
    pattern: &[u8],
    out: &mut dyn Write,
    prefix: Option<OsString>,
    found_match: &mut bool,
    had_error: &mut bool,
) {
    let file = match File::open(path) {
        Ok(f) => f,
        Err(e) => {
            eprintln!("rust_grep: {}: {}", path.to_string_lossy(), e);
            *had_error = true;
            return;
        }
    };
    let mut reader = BufReader::new(file);
    match search_stream(&mut reader, pattern, out, prefix.as_ref()) {
        Ok(f) => {
            *found_match = *found_match || f;
        }
        Err(e) => {
            eprintln!("rust_grep: {}: {}", path.to_string_lossy(), e);
            *had_error = true;
        }
    }
}

fn traverse_dir(dir: &Path, out_files: &mut Vec<OsString>, had_error: &mut bool) {
    let entries = match fs::read_dir(dir) {
        Ok(e) => e,
        Err(e) => {
            eprintln!("rust_grep: {}: {}", dir.to_string_lossy(), e);
            *had_error = true;
            return;
        }
    };

    let mut names: Vec<OsString> = Vec::new();
    for entry in entries.flatten() {
        names.push(entry.file_name());
    }
    names.sort();

    for name in names {
        let full = dir.join(&name);
        let meta = match fs::symlink_metadata(&full) {
            Ok(m) => m,
            Err(e) => {
                eprintln!("rust_grep: {}: {}", full.to_string_lossy(), e);
                *had_error = true;
                continue;
            }
        };

        if meta.file_type().is_symlink() {
            continue;
        }
        if meta.is_dir() {
            traverse_dir(&full, out_files, had_error);
        } else if meta.is_file() {
            out_files.push(full.into_os_string());
        }
    }
}

fn main() {
    let args: Vec<OsString> = std::env::args_os().collect();
    let mut pattern: Option<OsString> = None;
    let mut files: Vec<OsString> = Vec::new();
    let mut with_filename: Option<bool> = None;
    let mut recursive: bool = false;
    let mut after_ddash: bool = false;
    let mut pattern_set: bool = false;

    let mut i = 1;
    while i < args.len() {
        let arg = &args[i];

        if after_ddash {
            if !pattern_set {
                pattern = Some(arg.clone());
                pattern_set = true;
            } else {
                files.push(arg.clone());
            }
            i += 1;
            continue;
        }

        let bytes = arg.as_bytes();

        if bytes == b"--" {
            after_ddash = true;
            i += 1;
            continue;
        }

        if bytes.len() > 1 && bytes[0] == b'-' {
            if bytes.len() > 2 && bytes[1] == b'-' {
                let opt = &bytes[2..];
                match opt {
                    b"with-filename" => {
                        with_filename = Some(true);
                    }
                    b"no-filename" => {
                        with_filename = Some(false);
                    }
                    b"recursive" => {
                        recursive = true;
                    }
                    _ => {
                        eprintln!(
                            "rust_grep: unsupported option: --{}",
                            String::from_utf8_lossy(opt)
                        );
                        process::exit(2);
                    }
                }
            } else {
                let mut j = 1;
                while j < bytes.len() {
                    match bytes[j] {
                        b'H' => with_filename = Some(true),
                        b'h' => with_filename = Some(false),
                        b'r' => recursive = true,
                        _ => {
                            eprintln!(
                                "rust_grep: unsupported option: -{}",
                                String::from_utf8_lossy(&bytes[j..j + 1])
                            );
                            process::exit(2);
                        }
                    }
                    j += 1;
                }
            }
            i += 1;
            continue;
        }

        if !pattern_set {
            pattern = Some(arg.clone());
            pattern_set = true;
        } else {
            files.push(arg.clone());
        }
        i += 1;
    }

    let pattern_bytes: Vec<u8> = if let Some(p) = &pattern {
        p.as_bytes().to_vec()
    } else {
        eprintln!("rust_grep: no PATTERN given");
        eprintln!("Usage: rust_grep [options] PATTERN [FILE...]");
        process::exit(2);
    };

    let mut had_error = false;
    let mut found_match = false;
    let stdout = io::stdout();
    let mut out = stdout.lock();

    if files.is_empty() {
        let need_prefix = matches!(with_filename, Some(true));
        let prefix = if need_prefix {
            Some(OsString::from("(standard input)"))
        } else {
            None
        };
        let mut stdin = io::stdin();
        match search_stream(&mut stdin, &pattern_bytes, &mut out, prefix.as_ref()) {
            Ok(f) => found_match = f,
            Err(e) => {
                eprintln!("rust_grep: error reading stdin: {}", e);
                had_error = true;
            }
        }
    } else if recursive {
        let mut has_directory = false;
        for f in &files {
            if let Ok(meta) = fs::metadata(f) {
                if meta.is_dir() {
                    has_directory = true;
                }
            }
        }

        let need_prefix = match with_filename {
            Some(true) => true,
            Some(false) => false,
            None => files.len() > 1 || has_directory,
        };

        for f in &files {
            let path = Path::new(f);
            match fs::metadata(path) {
                Ok(meta) if meta.is_dir() => {
                    let mut sub_files = Vec::new();
                    traverse_dir(path, &mut sub_files, &mut had_error);
                    for sf in &sub_files {
                        let prefix = if need_prefix {
                            Some(sf.clone())
                        } else {
                            None
                        };
                        search_file(sf, &pattern_bytes, &mut out, prefix, &mut found_match, &mut had_error);
                    }
                }
                Ok(meta) if meta.is_file() => {
                    let prefix = if need_prefix {
                        Some(f.clone())
                    } else {
                        None
                    };
                    search_file(f, &pattern_bytes, &mut out, prefix, &mut found_match, &mut had_error);
                }
                Ok(_) => {
                    eprintln!("rust_grep: {}: not a regular file", path.to_string_lossy());
                    had_error = true;
                }
                Err(e) => {
                    eprintln!("rust_grep: {}: {}", path.to_string_lossy(), e);
                    had_error = true;
                }
            }
        }
    } else {
        let need_prefix = match with_filename {
            Some(true) => true,
            Some(false) => false,
            None => files.len() > 1,
        };

        for f in &files {
            let path = Path::new(f);
            match fs::metadata(path) {
                Ok(meta) if meta.is_dir() => {
                    eprintln!("rust_grep: {}: Is a directory", path.to_string_lossy());
                    had_error = true;
                }
                Ok(meta) if meta.is_file() => {
                    let prefix = if need_prefix {
                        Some(f.clone())
                    } else {
                        None
                    };
                    search_file(f, &pattern_bytes, &mut out, prefix, &mut found_match, &mut had_error);
                }
                Ok(_) => {
                    eprintln!("rust_grep: {}: not a regular file", path.to_string_lossy());
                    had_error = true;
                }
                Err(e) => {
                    eprintln!("rust_grep: {}: {}", path.to_string_lossy(), e);
                    had_error = true;
                }
            }
        }
    }

    if had_error {
        process::exit(2);
    } else if found_match {
        process::exit(0);
    } else {
        process::exit(1);
    }
}
