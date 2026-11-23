use std::io::{self, Read, Write};
use std::process;
use std::fs::File;

fn handle_operand(arg: &str) {
    match File::open(arg) {
        Ok(_) => {}
        Err(e) => {
            let full_msg = e.to_string();
            let msg = full_msg
                .split(" (os error ")
                .next()
                .unwrap_or(&full_msg);
            eprintln!("sort: cannot read: {}: {}", arg, msg);
            process::exit(2);
        }
    }
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let program_args = &args[1..];

    let mut reverse = false;
    let mut seen_double_dash = false;

    for arg in program_args {
        if seen_double_dash {
            handle_operand(arg);
        }
        if arg == "--" {
            seen_double_dash = true;
        } else if arg == "-r" || arg == "--reverse" {
            reverse = true;
        } else if arg.starts_with("--") {
            eprintln!("sort: unrecognized option '{}'\nTry 'sort --help' for more information.", arg);
            process::exit(2);
        } else if arg.starts_with('-') && arg.len() > 1 {
            for c in arg[1..].chars() {
                if c != 'r' {
                    eprintln!("sort: unrecognized option '{}'\nTry 'sort --help' for more information.", arg);
                    process::exit(2);
                }
            }
            reverse = true;
        } else {
            handle_operand(arg);
        }
    }

    let mut input = Vec::new();
    if let Err(e) = io::stdin().read_to_end(&mut input) {
        eprintln!("rust_sort: error: failed to read input: {}", e);
        process::exit(2);
    }

    if input.is_empty() {
        process::exit(0);
    }

    let mut records: Vec<&[u8]> = input.split(|&b| b == b'\n').collect();
    if input.last() == Some(&b'\n') {
        records.pop();
    }

    if reverse {
        records.sort_by(|a, b| b.cmp(a));
    } else {
        records.sort();
    }

    let mut out = io::stdout().lock();
    for record in &records {
        if let Err(e) = out.write_all(record).and_then(|_| out.write_all(b"\n")) {
            eprintln!("rust_sort: error: failed to write output: {}", e);
            process::exit(2);
        }
    }
    if let Err(e) = out.flush() {
        eprintln!("rust_sort: error: failed to flush output: {}", e);
        process::exit(2);
    }
}
