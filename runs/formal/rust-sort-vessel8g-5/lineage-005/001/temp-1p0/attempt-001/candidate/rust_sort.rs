use std::fs::File;
use std::io::{self, Read, Write};

fn os_error_msg(e: &io::Error) -> String {
    let s = e.to_string();
    match s.find(" (os error") {
        Some(pos) => s[..pos].to_string(),
        None => s,
    }
}

fn unknown_option(opt: &str) -> ! {
    eprint!("sort: unrecognized option '{}'\nTry 'sort --help' for more information.\n", opt);
    std::process::exit(2)
}

fn extra_operand(arg: &str) -> ! {
    eprint!("sort: extra operand '{}'\nTry 'sort --help' for more information.\n", arg);
    std::process::exit(2)
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();

    let mut reverse = false;
    let mut seen_ddash = false;
    let mut file_operand: Option<String> = None;

    for arg in &args {
        if seen_ddash {
            extra_operand(arg);
        }
        if arg == "--" {
            seen_ddash = true;
            continue;
        }
        if arg == "-" {
            extra_operand(arg);
        }
        if arg.starts_with("--") {
            match arg.as_str() {
                "--reverse" => { reverse = true; }
                _ => unknown_option(arg),
            }
            continue;
        }
        if arg.starts_with('-') && arg.len() > 1 {
            for c in arg[1..].chars() {
                match c {
                    'r' => { reverse = true; }
                    _ => {
                        let opt = format!("-{}", c);
                        unknown_option(&opt);
                    }
                }
            }
            continue;
        }
        if file_operand.is_some() {
            extra_operand(arg);
        }
        file_operand = Some(arg.clone());
    }

    let mut input: Vec<u8> = Vec::new();
    match file_operand {
        Some(path) => {
            let mut f = match File::open(&path) {
                Ok(f) => f,
                Err(e) => {
                    eprintln!("sort: cannot read: {}: {}", path, os_error_msg(&e));
                    std::process::exit(2);
                }
            };
            if let Err(e) = f.read_to_end(&mut input) {
                eprintln!("sort: cannot read: {}: {}", path, os_error_msg(&e));
                std::process::exit(2);
            }
        }
        None => {
            let mut stdin = io::stdin().lock();
            if let Err(e) = stdin.read_to_end(&mut input) {
                eprintln!("sort: cannot read input: {}", os_error_msg(&e));
                std::process::exit(2);
            }
        }
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

    if reverse {
        records.sort_unstable_by(|a, b| b.cmp(a));
    } else {
        records.sort_unstable_by(|a, b| a.cmp(b));
    }

    let stdout = io::stdout();
    let mut out = stdout.lock();
    for rec in &records {
        if out.write_all(rec).is_err() || out.write_all(b"\n").is_err() {
            eprintln!("sort: cannot write output");
            std::process::exit(2);
        }
    }
    if out.flush().is_err() {
        eprintln!("sort: cannot write output");
        std::process::exit(2);
    }
}
