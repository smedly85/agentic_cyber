use std::io::{self, Read, Write};

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let arg_list = &args[1..];

    // `--` is the only recognized token; it ends option parsing and
    // admits no operands.  Every other token is an unknown option or
    // an operand, both fatal.
    for arg in arg_list {
        if arg == "--" {
            continue;
        }
        if arg.starts_with('-') {
            eprintln!("sort: unrecognized option '{}'", arg);
            eprintln!("Try 'sort --help' for more information.");
            std::process::exit(2);
        }
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
    records.sort();

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
