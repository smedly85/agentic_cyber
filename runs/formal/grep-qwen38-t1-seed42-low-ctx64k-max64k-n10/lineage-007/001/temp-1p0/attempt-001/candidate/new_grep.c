#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/stat.h>

static char *read_line(FILE *fp, size_t *out_len) {
    size_t capacity = 256;
    size_t len = 0;
    char *buf = malloc(capacity);
    if (!buf) return NULL;

    int c;
    while ((c = fgetc(fp)) != EOF) {
        if (len + 1 >= capacity) {
            capacity *= 2;
            char *tmp = realloc(buf, capacity);
            if (!tmp) { free(buf); return NULL; }
            buf = tmp;
        }
        buf[len++] = (char)c;
        if (c == '\n') break;
    }

    if (len == 0) {
        free(buf);
        return NULL;
    }
    *out_len = len;
    return buf;
}

static int mem_contains(const char *hay, size_t hay_len,
                        const char *pat, size_t pat_len) {
    if (pat_len == 0) return 1;
    if (pat_len > hay_len) return 0;
    for (size_t i = 0; i <= hay_len - pat_len; i++) {
        if (memcmp(hay + i, pat, pat_len) == 0) return 1;
    }
    return 0;
}

static int write_selected_line(const char *line, size_t len,
                               const char *prefix, size_t prefix_len) {
    size_t out_len = len;
    if (out_len > 0 && line[out_len - 1] == '\n') out_len--;

    if (prefix_len > 0) {
        if (fwrite(prefix, 1, prefix_len, stdout) != prefix_len) return -1;
        if (fputc(':', stdout) == EOF) return -1;
    }
    if (out_len > 0) {
        if (fwrite(line, 1, out_len, stdout) != out_len) return -1;
    }
    if (fputc('\n', stdout) == EOF) return -1;
    return 0;
}

static int grep_file(const char *filename, const char *pattern,
                     size_t pattern_len, int expect_prefix) {
    struct stat st;
    if (stat(filename, &st) == 0 && S_ISDIR(st.st_mode)) {
        fprintf(stderr, "new_grep: %s: Is a directory\n", filename);
        return 2;
    }

    FILE *fp = fopen(filename, "rb");
    if (fp == NULL) {
        fprintf(stderr, "new_grep: %s: No such file or directory\n", filename);
        return 2;
    }

    int found = 0;
    size_t line_len;
    while (1) {
        char *line = read_line(fp, &line_len);
        if (!line) break;
        if (mem_contains(line, line_len, pattern, pattern_len)) {
            if (write_selected_line(line, line_len,
                    expect_prefix ? filename : "",
                    expect_prefix ? strlen(filename) : 0) != 0) {
                free(line);
                fclose(fp);
                fprintf(stderr, "new_grep: write error\n");
                return 2;
            }
            found = 1;
        }
        free(line);
    }
    fclose(fp);
    return found ? 0 : 1;
}

static int grep_stdin(const char *pattern, size_t pattern_len, int with_filename) {
    static const char *stdin_name = "(standard input)";
    int found = 0;
    size_t line_len;
    while (1) {
        char *line = read_line(stdin, &line_len);
        if (!line) break;
        if (mem_contains(line, line_len, pattern, pattern_len)) {
            if (write_selected_line(line, line_len,
                    with_filename ? stdin_name : "",
                    with_filename ? strlen(stdin_name) : 0) != 0) {
                free(line);
                fprintf(stderr, "new_grep: write error\n");
                return 2;
            }
            found = 1;
        }
        free(line);
    }
    return found ? 0 : 1;
}

static void print_usage(void) {
    fprintf(stderr, "Usage: new_grep PATTERN [FILE...]\n");
}

int main(int argc, char *argv[]) {
    argc--;
    argv++;

    int with_filename = 0;
    int after_separator = 0;
    const char *pattern = NULL;
    const char *files[1024];
    int file_count = 0;

    for (int i = 0; i < argc; i++) {
        if (!after_separator) {
            if (strcmp(argv[i], "--") == 0) {
                after_separator = 1;
                continue;
            }
            if (argv[i][0] == '-' && strlen(argv[i]) > 1) {
                if (strcmp(argv[i], "-H") == 0 ||
                    strcmp(argv[i], "--with-filename") == 0) {
                    with_filename = 1;
                    continue;
                }
                fprintf(stderr, "new_grep: invalid option -- %s\n", argv[i]);
                print_usage();
                return 2;
            }
        }

        if (pattern == NULL) {
            pattern = argv[i];
        } else {
            if (file_count < 1024) {
                files[file_count++] = argv[i];
            }
        }
    }

    if (pattern == NULL) {
        print_usage();
        return 2;
    }

    size_t pattern_len = strlen(pattern);

    if (file_count == 0) {
        return grep_stdin(pattern, pattern_len, with_filename);
    }

    int expect_prefix = with_filename || (file_count >= 2);
    int exit_code = 1;

    for (int i = 0; i < file_count; i++) {
        int result = grep_file(files[i], pattern, pattern_len, expect_prefix);
        if (result == 2) {
            exit_code = 2;
        } else if (result == 0 && exit_code != 2) {
            exit_code = 0;
        }
    }
    return exit_code;
}
