use std::env;
use std::ffi::OsString;
use std::fs::{self, File};
use std::io::{self, BufReader, BufWriter, Read, Write};
use std::os::unix::ffi::{OsStrExt, OsStringExt};
use std::process;

fn fold_byte(b: u8) -> u8 {
    if b >= b'A' && b <= b'Z' {
        b + 0x20
    } else {
        b
    }
}

fn search_stream(
    pattern: &[u8],
    mut reader: impl Read,
    mut output: impl Write,
    prefix: Option<&[u8]>,
    ignore_case: bool,
) -> io::Result<bool> {
    let mut line_buf: Vec<u8> = Vec::with_capacity(4096);
    let mut matched_any = false;
    let mut chunk = [0u8; 8192];

    loop {
        let n = reader.read(&mut chunk)?;
        if n == 0 {
            if !line_buf.is_empty() {
                if pattern.is_empty()
                    || (ignore_case && line_buf.windows(pattern.len())
                        .any(|w| w.iter().zip(pattern).all(|(a, b)| fold_byte(*a) == *b)))
                    || (!ignore_case && line_buf.windows(pattern.len()).any(|w| w == pattern))
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
                    || (ignore_case && line_buf.windows(pattern.len())
                        .any(|w| w.iter().zip(pattern).all(|(a, b)| fold_byte(*a) == *b)))
                    || (!ignore_case && line_buf.windows(pattern.len()).any(|w| w == pattern))
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

fn join_path(base: &[u8], name: &[u8]) -> Vec<u8> {
    let mut result = Vec::with_capacity(base.len() + 1 + name.len());
    result.extend_from_slice(base);
    if !base.is_empty() && base[base.len() - 1] != b'/' {
        result.push(b'/');
    }
    result.extend_from_slice(name);
    result
}

fn recursive_traverse(
    root: &[u8],
    pattern: &[u8],
    output: &mut impl Write,
    use_prefix: bool,
    ignore_case: bool,
) -> (bool, bool) {
    let mut matched_any = false;
    let mut any_error = false;

    // Work stack: (path_bytes, is_directory)
    // LIFO: push children in reverse so they pop in ascending order (pre-order)
    let mut stack: Vec<(Vec<u8>, bool)> = Vec::new();
    stack.push((root.to_vec(), true));

    while let Some((path, is_dir)) = stack.pop() {
        if is_dir {
            let os_path = OsString::from_vec(path.clone());
            let dir = match fs::read_dir(&os_path) {
                Ok(d) => d,
                Err(e) => {
                    eprintln!("rust_grep: {}: {}", os_path.to_string_lossy(), e);
                    any_error = true;
                    continue;
                }
            };

            let mut entry_list: Vec<Vec<u8>> = Vec::new();
            for entry in dir {
                match entry {
                    Ok(e) => {
                        let name = e.file_name().as_bytes().to_vec();
                        entry_list.push(name);
                    }
                    Err(e) => {
                        eprintln!("rust_grep: {}: {}", os_path.to_string_lossy(), e);
                        any_error = true;
                    }
                }
            }

            entry_list.sort();

            // Push in reverse so first entry is popped first (pre-order)
            for name in entry_list.iter().rev() {
                let child_path = join_path(&path, name);
                let os_child = OsString::from_vec(child_path.clone());
                let sm = match fs::symlink_metadata(&os_child) {
                    Ok(m) => m,
                    Err(e) => {
                        eprintln!("rust_grep: {}: {}", os_child.to_string_lossy(), e);
                        any_error = true;
                        continue;
                    }
                };

                if sm.file_type().is_symlink() {
                    continue;
                }

                if sm.is_dir() {
                    stack.push((child_path, true));
                } else if sm.is_file() {
                    stack.push((child_path, false));
                }
            }
        } else {
            let os_path = OsString::from_vec(path.clone());
            let file = match File::open(&os_path) {
                Ok(f) => f,
                Err(e) => {
                    eprintln!("rust_grep: {}: {}", os_path.to_string_lossy(), e);
                    any_error = true;
                    continue;
                }
            };

            let reader = BufReader::new(file);
            let prefix: Option<Vec<u8>> = if use_prefix {
                let mut p = path.clone();
                p.push(b':');
                Some(p)
            } else {
                None
            };

            match search_stream(pattern, reader, &mut *output, prefix.as_deref(), ignore_case) {
                Ok(m) => {
                    if m {
                        matched_any = true;
                    }
                }
                Err(e) => {
                    eprintln!("rust_grep: {}: {}", os_path.to_string_lossy(), e);
                    any_error = true;
                }
            }
        }
    }

    (matched_any, any_error)
}

fn main() {
    let args: Vec<OsString> = env::args_os().skip(1).collect();

    let mut pattern: Option<OsString> = None;
    let mut files: Vec<OsString> = Vec::new();
    let mut end_of_options = false;
    let mut filename_policy: Option<bool> = None; // None=default, Some(true)=with, Some(false)=without
    let mut recursive = false;
    let mut ignore_case = false;

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
            } else if bytes == b"--recursive" {
                recursive = true;
            } else if bytes == b"--ignore-case" {
                ignore_case = true;
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
                } else if c == b'r' {
                    recursive = true;
                } else if c == b'i' {
                    ignore_case = true;
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
    let pattern_bytes: Vec<u8> = if ignore_case {
        pattern_bytes.iter().map(|&b| fold_byte(b)).collect()
    } else {
        pattern_bytes
    };

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
        match search_stream(&pattern_bytes, &mut reader, &mut out, stdin_prefix.as_deref(), ignore_case) {
            Ok(matched) => {
                any_match = matched;
            }
            Err(_) => {
                any_error = true;
            }
        }
    } else {
        // Determine which operands are directories (follows symlinks)
        let dir_flags: Vec<bool> = files
            .iter()
            .map(|f| fs::metadata(f).map(|m| m.is_dir()).unwrap_or(false))
            .collect();
        let any_is_dir = dir_flags.iter().any(|&d| d);

        // Directory without -r is an error
        for (i, is_dir) in dir_flags.iter().enumerate() {
            if *is_dir && !recursive {
                let display = files[i].to_string_lossy();
                eprintln!("rust_grep: {}: Is a directory", display);
                any_error = true;
            }
        }

        // Global prefix decision
        let should_prefix = match filename_policy {
            Some(true) => true,
            Some(false) => false,
            None => any_is_dir || files.len() >= 2,
        };

        for (i, file) in files.iter().enumerate() {
            if dir_flags[i] && recursive {
                // Recursive traversal
                let root_bytes = file.as_bytes().to_vec();
                let (m, e) = recursive_traverse(
                    &root_bytes,
                    &pattern_bytes,
                    &mut out,
                    should_prefix,
                    ignore_case,
                );
                if m {
                    any_match = true;
                }
                if e {
                    any_error = true;
                }
            } else if dir_flags[i] {
                // Already diagnosed as error above; skip
                continue;
            } else {
                // Regular file (or symlink to file)
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

                let mut reader = BufReader::new(f);
                let prefix_bytes: Option<Vec<u8>> = if should_prefix {
                    let mut p = file_bytes;
                    p.push(b':');
                    Some(p)
                } else {
                    None
                };

                match search_stream(&pattern_bytes, &mut reader, &mut out, prefix_bytes.as_deref(), ignore_case) {
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
