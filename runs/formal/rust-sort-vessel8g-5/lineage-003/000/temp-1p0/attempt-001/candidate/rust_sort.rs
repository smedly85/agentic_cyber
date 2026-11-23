use std::io::{self, Read, Write};
use std::process;

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();

    let mut file_operands: Vec<String> = Vec::new();
    let mut has_double_dash = false;

    if !args.is_empty() {
        for arg in &args {
            if !has_double_dash && arg == "--" {
                has_double_dash = true;
            } else if !has_double_dash && arg.starts_with('-') {
                writeln!(io::stderr(), "sort: unrecognized option '{}'", arg).unwrap_or(());
                writeln!(io::stderr(), "Try 'sort --help' for more information.").unwrap_or(());
                process::exit(2);
            } else {
                file_operands.push(arg.clone());
            }
        }
    }

    // Read input: file operands (if any) followed by stdin.
    let mut input = Vec::new();

    if !file_operands.is_empty() {
        for name in &file_operands {
            match std::fs::OpenOptions::new().read(true).open(name) {
                Ok(mut file) => {
                    if let Err(e) = file.read_to_end(&mut input) {
                        writeln!(io::stderr(), "sort: read error: {}", e).unwrap_or(());
                        process::exit(2);
                    }
                }
                Err(e) => {
                    let msg = e.to_string();
                    let msg = msg.split(" (").next().unwrap_or(&msg).to_string();
                    writeln!(io::stderr(), "sort: cannot read: {}: {}", name, msg).unwrap_or(());
                    process::exit(2);
                }
            }
        }
    }

    if let Err(e) = io::stdin().read_to_end(&mut input) {
        writeln!(io::stderr(), "sort: read error: {}", e).unwrap_or(());
        process::exit(2);
    }

    // Split into records: segments delimited by '\n' (0x0A).
    let mut records: Vec<&[u8]> = if input.is_empty() {
        Vec::new()
    } else {
        let mut parts: Vec<&[u8]> = input.split(|&b| b == b'\n').collect();
        if input.last() == Some(&b'\n') {
            parts.pop();
        }
        parts
    };

    // Sort in unsigned bytewise lexicographic ascending order.
    records.sort();

    // Emit each record followed by a newline.
    let mut out = io::stdout();
    for record in &records {
        if out.write_all(record).is_err() || out.write_all(b"\n").is_err() {
            writeln!(io::stderr(), "sort: write error").unwrap_or(());
            process::exit(2);
        }
    }
    if out.flush().is_err() {
        writeln!(io::stderr(), "sort: flush error").unwrap_or(());
        process::exit(2);
    }
}
