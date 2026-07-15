# new_sort

`new_sort` reads lines from standard input, sorts them in ascending bytewise
lexicographic order, and writes the sorted lines to standard output. It accepts
no command-line arguments.

## Build

From the repository root, run:

```sh
make
```

This creates `build/new_sort`.

## Run

Provide lines through standard input:

```sh
printf "pear\napple\nbanana\n" | build/new_sort
```

## Test

```sh
make test
```

## Clean

Remove generated files with:

```sh
make clean
```
