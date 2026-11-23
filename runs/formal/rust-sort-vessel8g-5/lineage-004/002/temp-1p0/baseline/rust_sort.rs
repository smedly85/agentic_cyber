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
        if arg.starts_with("--") {
            fail_unknown_option(arg);
        }
        if arg.starts_with('-') && arg.len() > 1 {
            for ch in arg[1..].chars() {
                if ch == 'r' {
                    reverse = true;
                } else {
                    fail_unknown_option(arg);
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

    let mut ranges: Vec<(usize, usize)> = Vec::new();
    if !input.is_empty() {
        let mut start = 0usize;
        for (i, &b) in input.iter().enumerate() {
            if b == b'\n' {
                ranges.push((start, i - start));
                start = i + 1;
            }
        }
        if start < input.len() {
            ranges.push((start, input.len() - start));
        }
    }

    if reverse {
        ranges.sort_by(|a, b| {
            input[b.0..b.0 + b.1].cmp(&input[a.0..a.0 + a.1])
        });
    } else {
        ranges.sort_by(|a, b| {
            input[a.0..a.0 + a.1].cmp(&input[b.0..b.0 + b.1])
        });
    }

    let stdout = io::stdout();
    let mut out = stdout.lock();
    for &(start, len) in &ranges {
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
