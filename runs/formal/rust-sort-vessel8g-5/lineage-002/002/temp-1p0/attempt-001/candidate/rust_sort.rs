use std::io::{self, Read, Write};

fn cmp_ignore_case(a: &[u8], b: &[u8]) -> std::cmp::Ordering {
    for (x, y) in a.iter().zip(b.iter()) {
        let xf = if (0x41u8..=0x5Au8).contains(x) { x + 32 } else { *x };
        let yf = if (0x41u8..=0x5Au8).contains(y) { y + 32 } else { *y };
        if xf != yf {
            return xf.cmp(&yf);
        }
    }
    a.cmp(b)
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let arg_list = &args[1..];

    let mut reverse = false;
    let mut ignore_case = false;

    for arg in arg_list {
        if arg == "--" {
            continue;
        }
        if arg == "--reverse" {
            reverse = true;
            continue;
        }
        if arg == "--ignore-case" {
            ignore_case = true;
            continue;
        }
        if arg.starts_with("--") {
            eprintln!("sort: unrecognized option '{}'", arg);
            eprintln!("Try 'sort --help' for more information.");
            std::process::exit(2);
        }
        if arg.starts_with('-') {
            let cluster = &arg[1..];
            if cluster.is_empty() {
                eprintln!("sort: unrecognized option '-'");
                eprintln!("Try 'sort --help' for more information.");
                std::process::exit(2);
            }
            for c in cluster.chars() {
                match c {
                    'r' => reverse = true,
                    'f' => ignore_case = true,
                    _ => {
                        eprintln!("sort: unrecognized option '{}'", arg);
                        eprintln!("Try 'sort --help' for more information.");
                        std::process::exit(2);
                    }
                }
            }
            continue;
        }
        // operand
        match std::fs::metadata(arg) {
            Err(e) => {
                let msg = e.to_string();
                let stripped = if let Some(pos) = msg.rfind(" (os error ") {
                    &msg[..pos]
                } else {
                    &msg
                };
                eprintln!("sort: cannot read: {}: {}", arg, stripped);
                std::process::exit(2);
            }
            Ok(m) if m.is_dir() => {
                eprintln!("sort: cannot read: {}: Is a directory", arg);
                std::process::exit(2);
            }
            Ok(_) => {
                eprintln!("sort: cannot read: {}: file operands are not supported", arg);
                std::process::exit(2);
            }
        }
    }

    // Read all of stdin as bytes.
    let mut input: Vec<u8> = Vec::new();
    if let Err(e) = io::stdin().read_to_end(&mut input) {
        eprintln!("rust_sort: reading input: {e}");
        std::process::exit(2);
    }

    // Split into newline-delimited records.
    // A trailing non-empty unterminated chunk is still a record.
    // Empty input yields zero records.
    let mut records: Vec<&[u8]> = Vec::new();
    let mut start = 0usize;
    for (i, &b) in input.iter().enumerate() {
        if b == b'\n' {
            records.push(&input[start..i]);
            start = i + 1;
        }
    }
    if start < input.len() {
        records.push(&input[start..]);
    }

    // Unsigned bytewise lexicographic ascending (LC_ALL=C order).
    // Duplicates are preserved; record contents are not modified.
    records.sort_by(|a, b| {
        let primary = if ignore_case {
            cmp_ignore_case(a, b)
        } else {
            a.cmp(b)
        };
        if reverse { primary.reverse() } else { primary }
    });

    // Emit every record followed by a newline.
    let stdout = io::stdout();
    let mut out = stdout.lock();
    for rec in &records {
        if out.write_all(rec).is_err() || out.write_all(b"\n").is_err() {
            eprintln!("rust_sort: writing output");
            std::process::exit(2);
        }
    }
    if out.flush().is_err() {
        eprintln!("rust_sort: writing output");
        std::process::exit(2);
    }
}
