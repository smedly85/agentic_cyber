use std::collections::HashSet;
use std::io::{self, Read, Write};

fn fold_byte(b: u8) -> u8 {
    if b'A' <= b && b <= b'Z' {
        b + 32
    } else {
        b
    }
}

fn compute_key(rec: &[u8], ignore_case: bool) -> Vec<u8> {
    if ignore_case {
        rec.iter().map(|b| fold_byte(*b)).collect()
    } else {
        rec.to_vec()
    }
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let arg_list = &args[1..];

    let mut reverse = false;
    let mut ignore_case = false;
    let mut unique = false;

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
        if arg == "--unique" {
            unique = true;
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
                    'u' => unique = true,
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

    // Split into newline-delimited records (borrowed slices into `input`).
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

    if records.is_empty() {
        return;
    }

    // Compute comparison keys once.
    let keys: Vec<Vec<u8>> = records
        .iter()
        .map(|rec| compute_key(rec, ignore_case))
        .collect();

    let result: Vec<usize> = if unique {
        // Deduplicate by key, keeping first in input order.
        let mut seen: HashSet<Vec<u8>> = HashSet::new();
        let mut unique_idx: Vec<usize> = Vec::new();
        for i in 0..records.len() {
            if seen.insert(keys[i].clone()) {
                unique_idx.push(i);
            }
        }
        // Sort by comparison key only (no last-resort; keys are unique here).
        unique_idx.sort_by(|&a, &b| {
            let ord = keys[a].cmp(&keys[b]);
            if reverse {
                ord.reverse()
            } else {
                ord
            }
        });
        unique_idx
    } else {
        // Sort all records.
        let mut indices: Vec<usize> = (0..records.len()).collect();
        indices.sort_by(|&a, &b| {
            let primary = if ignore_case {
                // Folded key first, original bytes as last-resort.
                keys[a]
                    .cmp(&keys[b])
                    .then_with(|| records[a].cmp(records[b]))
            } else {
                keys[a].cmp(&keys[b])
            };
            if reverse {
                primary.reverse()
            } else {
                primary
            }
        });
        indices
    };

    // Emit every selected record followed by a newline.
    let stdout = io::stdout();
    let mut out = stdout.lock();
    for &idx in &result {
        if out.write_all(records[idx]).is_err() || out.write_all(b"\n").is_err() {
            eprintln!("rust_sort: writing output");
            std::process::exit(2);
        }
    }
    if out.flush().is_err() {
        eprintln!("rust_sort: writing output");
        std::process::exit(2);
    }
}
