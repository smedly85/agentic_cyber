use std::io::{self, Read, Write};
use std::process;

fn main() {
    std::panic::set_hook(Box::new(|_| {
        let _ = io::stderr().write_all(b"rust_sort: internal error\n");
        process::exit(2);
    }));

    let args: Vec<String> = std::env::args().skip(1).collect();
    let mut after_ddash = false;
    let mut reverse = false;
    let mut ignore_case = false;
    let mut unique = false;
    let mut check = false;

    for arg in &args {
        if after_ddash {
            fail_operand(arg);
        }
        if arg == "--" {
            after_ddash = true;
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
        if arg == "--check" {
            check = true;
            continue;
        }
        if arg.starts_with("--") {
            fail_unknown_option(arg);
        }
        if arg.starts_with('-') && arg.len() > 1 {
            for ch in arg[1..].chars() {
                match ch {
                    'r' => reverse = true,
                    'f' => ignore_case = true,
                    'u' => unique = true,
                    'c' => check = true,
                    _ => fail_unknown_option(arg),
                }
            }
            continue;
        }
        fail_operand(arg);
    }

    let mut input: Vec<u8> = Vec::new();
    if let Err(e) = io::stdin().read_to_end(&mut input) {
        eprintln!("rust_sort: {}", e);
        process::exit(2);
    }

    let mut records: Vec<(usize, usize, usize)> = Vec::new();
    if !input.is_empty() {
        let mut start = 0usize;
        for (i, &b) in input.iter().enumerate() {
            if b == b'\n' {
                let idx = records.len();
                records.push((start, i - start, idx));
                start = i + 1;
            }
        }
        if start < input.len() {
            let idx = records.len();
            records.push((start, input.len() - start, idx));
        }
    }

    if check {
        if records.len() <= 1 {
            process::exit(0);
        }
        for i in 0..records.len() - 1 {
            let a = &input[records[i].0..records[i].0 + records[i].1];
            let b = &input[records[i + 1].0..records[i + 1].0 + records[i + 1].1];
            let in_order = if unique {
                let cmp = cmp_primary(a, b, ignore_case);
                if reverse {
                    cmp == std::cmp::Ordering::Greater
                } else {
                    cmp == std::cmp::Ordering::Less
                }
            } else {
                let cmp = cmp_records(a, b, ignore_case);
                if reverse {
                    cmp != std::cmp::Ordering::Less
                } else {
                    cmp != std::cmp::Ordering::Greater
                }
            };
            if !in_order {
                let line = &input[records[i + 1].0..records[i + 1].0 + records[i + 1].1];
                let mut stderr = io::stderr().lock();
                let _ = stderr.write_all(b"sort: disorder: ");
                let _ = stderr.write_all(line);
                let _ = stderr.write_all(b"\n");
                process::exit(1);
            }
        }
        process::exit(0);
    }

    if reverse {
        records.sort_by(|a, b| {
            cmp_records(
                &input[b.0..b.0 + b.1],
                &input[a.0..a.0 + a.1],
                ignore_case,
            )
        });
    } else {
        records.sort_by(|a, b| {
            cmp_records(
                &input[a.0..a.0 + a.1],
                &input[b.0..b.0 + b.1],
                ignore_case,
            )
        });
    }

    let final_records: Vec<(usize, usize, usize)> = if unique {
        let mut out = Vec::new();
        let mut i = 0usize;
        while i < records.len() {
            let group_start = i;
            i += 1;
            while i < records.len() {
                let prev = &input[records[i - 1].0..records[i - 1].0 + records[i - 1].1];
                let cur = &input[records[i].0..records[i].0 + records[i].1];
                if are_duplicates(prev, cur, ignore_case) {
                    i += 1;
                } else {
                    break;
                }
            }
            let best = (group_start..i)
                .min_by_key(|&j| records[j].2)
                .unwrap();
            out.push(records[best]);
        }
        out
    } else {
        records
    };

    let stdout = io::stdout();
    let mut out = stdout.lock();
    for &(start, len, _idx) in &final_records {
        if let Err(e) = out.write_all(&input[start..start + len]) {
            eprintln!("rust_sort: {}", e);
            process::exit(2);
        }
        if let Err(e) = out.write_all(b"\n") {
            eprintln!("rust_sort: {}", e);
            process::exit(2);
        }
    }
    if let Err(e) = out.flush() {
        eprintln!("rust_sort: {}", e);
        process::exit(2);
    }
}

fn fail_unknown_option(opt: &str) -> ! {
    eprintln!(
        "sort: unrecognized option '{}'\nTry 'sort --help' for more information.",
        opt
    );
    process::exit(2);
}

fn fail_operand(file: &str) -> ! {
    match std::fs::File::open(file) {
        Err(e) => {
            let raw = e.to_string();
            let msg = match raw.rfind(" (os error ") {
                Some(pos) => raw[..pos].to_string(),
                None => raw,
            };
            eprintln!("sort: cannot read: {}: {}", file, msg);
        }
        Ok(_) => {
            eprintln!("sort: cannot read: {}: No such file or directory", file);
        }
    }
    process::exit(2);
}

fn cmp_records(a: &[u8], b: &[u8], ignore_case: bool) -> std::cmp::Ordering {
    if !ignore_case {
        return a.cmp(b);
    }
    let min_len = std::cmp::min(a.len(), b.len());
    for i in 0..min_len {
        let fa = if a[i] >= b'a' && a[i] <= b'z' { a[i] - 32 } else { a[i] };
        let fb = if b[i] >= b'a' && b[i] <= b'z' { b[i] - 32 } else { b[i] };
        if fa != fb {
            return fa.cmp(&fb);
        }
    }
    if a.len() != b.len() {
        return a.len().cmp(&b.len());
    }
    a.cmp(b)
}

fn cmp_primary(a: &[u8], b: &[u8], ignore_case: bool) -> std::cmp::Ordering {
    if !ignore_case {
        return a.cmp(b);
    }
    let min_len = std::cmp::min(a.len(), b.len());
    for i in 0..min_len {
        let fa = if a[i] >= b'a' && a[i] <= b'z' { a[i] - 32 } else { a[i] };
        let fb = if b[i] >= b'a' && b[i] <= b'z' { b[i] - 32 } else { b[i] };
        if fa != fb {
            return fa.cmp(&fb);
        }
    }
    a.len().cmp(&b.len())
}

fn are_duplicates(a: &[u8], b: &[u8], ignore_case: bool) -> bool {
    if !ignore_case {
        return a == b;
    }
    if a.len() != b.len() {
        return false;
    }
    for i in 0..a.len() {
        let fa = if a[i] >= b'a' && a[i] <= b'z' { a[i] - 32 } else { a[i] };
        let fb = if b[i] >= b'a' && b[i] <= b'z' { b[i] - 32 } else { b[i] };
        if fa != fb {
            return false;
        }
    }
    true
}
