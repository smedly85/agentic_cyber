use std::io::{self, Read, Write};

fn os_error_msg(e: &io::Error) -> String {
    let s = e.to_string();
    match s.find(" (os error") {
        Some(pos) => s[..pos].to_string(),
        None => s,
    }
}

fn reject_operand(arg: &str) -> ! {
    match std::fs::File::open(arg) {
        Err(e) => {
            eprint!("sort: cannot read: {}: {}\n", arg, os_error_msg(&e));
        }
        Ok(_) => {
            eprint!("sort: cannot read: {}: (file operands are not supported)\n", arg);
        }
    }
    std::process::exit(2)
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();

    let mut seen_ddash = false;
    for arg in &args {
        if arg == "--" {
            seen_ddash = true;
            continue;
        }
        if seen_ddash {
            reject_operand(arg);
        }
        if arg.starts_with('-') && arg.len() > 1 {
            eprint!("sort: unrecognized option '{}'\nTry 'sort --help' for more information.\n", arg);
            std::process::exit(2);
        }
        reject_operand(arg);
    }

    let mut input: Vec<u8> = Vec::new();
    let mut stdin = io::stdin().lock();
    if let Err(e) = stdin.read_to_end(&mut input) {
        eprintln!("rust_sort: cannot read input: {}", os_error_msg(&e));
        std::process::exit(2);
    }

    let mut records: Vec<&[u8]> = Vec::new();
    let mut start = 0;
    for (i, &b) in input.iter().enumerate() {
        if b == 0x0A {
            records.push(&input[start..i]);
            start = i + 1;
        }
    }
    if start < input.len() {
        records.push(&input[start..]);
    }

    records.sort_unstable_by(|a, b| a.cmp(b));

    let stdout = io::stdout();
    let mut out = stdout.lock();
    for rec in &records {
        if out.write_all(rec).is_err() || out.write_all(b"\n").is_err() {
            eprintln!("rust_sort: cannot write output");
            std::process::exit(2);
        }
    }
    if out.flush().is_err() {
        eprintln!("rust_sort: cannot write output");
        std::process::exit(2);
    }
}
