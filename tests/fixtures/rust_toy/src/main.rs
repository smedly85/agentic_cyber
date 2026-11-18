use std::env;
use std::process::ExitCode;

trait Transform {
    fn transform(&self, value: i64) -> i64;
}

struct Square;
struct Negate;

impl Transform for Square {
    fn transform(&self, value: i64) -> i64 {
        value * value
    }
}

impl Transform for Negate {
    fn transform(&self, value: i64) -> i64 {
        -value
    }
}

struct Accumulator {
    total: i64,
}

impl Accumulator {
    fn new() -> Self {
        Accumulator { total: 0 }
    }

    fn add(&mut self, value: i64) {
        self.total += value;
    }
}

fn parse_number(text: &str) -> Option<i64> {
    let (sign, digits) = match text.strip_prefix('-') {
        Some(rest) => (-1, rest),
        None => (1, text),
    };
    if digits.is_empty() || !digits.chars().all(is_digit_char) {
        return None;
    }
    digits.parse::<i64>().ok().map(|v| sign * v)
}

fn is_digit_char(c: char) -> bool {
    c.is_ascii_digit()
}

fn apply<T: Transform>(op: &T, value: i64) -> i64 {
    op.transform(value)
}

fn sum_all(items: &[String]) -> Option<i64> {
    let mut acc = Accumulator::new();
    for item in items {
        acc.add(parse_number(item)?);
    }
    Some(acc.total)
}

#[allow(dead_code)]
fn unused_debug() {
    println!("never called");
}

fn main() -> ExitCode {
    let args: Vec<String> = env::args().skip(1).collect();
    if args.is_empty() {
        eprintln!("usage: toy [-s|-n] NUM...");
        return ExitCode::from(2);
    }
    let (mode, rest) = match args[0].as_str() {
        "-s" | "-n" => (Some(args[0].clone()), &args[1..]),
        _ => (None, &args[..]),
    };
    let total = match sum_all(rest) {
        Some(t) => t,
        None => {
            eprintln!("toy: invalid number");
            return ExitCode::from(1);
        }
    };
    let total = match mode.as_deref() {
        Some("-s") => apply(&Square, total),
        Some("-n") => apply(&Negate, total),
        _ => total,
    };
    println!("{total}");
    ExitCode::SUCCESS
}
