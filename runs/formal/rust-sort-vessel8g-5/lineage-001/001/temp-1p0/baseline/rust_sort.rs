use std::io::{self, Read, Write};
use std::process;

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let program_args = &args[1..];
    if !program_args.is_empty() {
        if program_args.len() == 1 && program_args[0] == "--" {
            // bare "--" is valid
        } else {
            let bad = &program_args[0];
            if bad.starts_with('-') && bad != "--" {
                eprintln!("sort: unrecognized option '{}'\nTry 'sort --help' for more information.", bad);
            } else {
                eprintln!("sort: cannot read: {}: No such file or directory", bad);
            }
            process::exit(2);
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

    records.sort();

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
