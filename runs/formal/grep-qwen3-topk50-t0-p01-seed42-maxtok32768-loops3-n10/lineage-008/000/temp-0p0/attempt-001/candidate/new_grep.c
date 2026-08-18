#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <errno.h>
#include <limits.h>

#define CHUNK_SIZE 4096

static char *read_line(FILE *fp, size_t *len_out) {
    size_t capacity = CHUNK_SIZE;
    size_t len = 0;
    char *buf = malloc(capacity);
    if (!buf) return NULL;

    while (1) {
        int c = fgetc(fp);
        if (c == EOF) {
            if (ferror(fp)) {
                free(buf);
                return NULL;
            }
            if (len > 0) {
                break;
            }
            free(buf);
            return NULL;
        }
        if (c == '\n') {
            break;
        }
        if (len >= capacity - 1) {
            size_t new_cap = capacity * 2;
            if (new_cap <= capacity) {
                free(buf);
                return NULL;
            }
            char *new_buf = realloc(buf, new_cap);
            if (!new_buf) {
                free(buf);
                return NULL;
            }
            buf = new_buf;
            capacity = new_cap;
        }
        buf[len++] = (char)c;
    }

    buf[len] = '\0';
    *len_out = len;
    return buf;
}

static int matches(const char *line, size_t line_len, const char *pattern, size_t pat_len) {
    if (pat_len == 0) return 1;
    if (pat_len > line_len) return 0;
    return memmem(line, line_len, pattern, pat_len) != NULL;
}

static int write_line_with_prefix(const char *filename, const char *line, size_t len) {
    if (fprintf(stdout, "%s:", filename) < 0) return -1;
    if (len > 0) {
        if (fwrite(line, 1, len, stdout) != len) return -1;
    }
    if (fputc('\n', stdout) == EOF) return -1;
    return 0;
}

static int write_line(const char *line, size_t len) {
    if (len > 0) {
        if (fwrite(line, 1, len, stdout) != len) return -1;
    }
    if (fputc('\n', stdout) == EOF) return -1;
    return 0;
}

static int search_file(const char *filename, const char *pattern, size_t pat_len,
                       int prefix_filename) {
    FILE *fp = fopen(filename, "rb");
    if (!fp) {
        fprintf(stderr, "%s: %s\n", filename, strerror(errno));
        return 2;
    }

    struct stat st;
    if (fstat(fileno(fp), &st) == 0 && S_ISDIR(st.st_mode)) {
        fprintf(stderr, "%s: Is a directory\n", filename);
        fclose(fp);
        return 2;
    }

    int matched = 0;
    int error_occurred = 0;

    while (1) {
        size_t line_len;
        char *line = read_line(fp, &line_len);
        if (!line && ferror(fp)) {
            fprintf(stderr, "%s: %s\n", filename, strerror(errno));
            error_occurred = 1;
            break;
        }
        if (!line) break;

        if (matches(line, line_len, pattern, pat_len)) {
            matched = 1;
            if (prefix_filename) {
                if (write_line_with_prefix(filename, line, line_len) < 0) {
                    error_occurred = 1;
                    break;
                }
            } else {
                if (write_line(line, line_len) < 0) {
                    error_occurred = 1;
                    break;
                }
            }
        }
        free(line);
    }

    fclose(fp);

    if (error_occurred) return 2;
    return matched ? 0 : 1;
}

static void usage(void) {
    fprintf(stderr, "Usage: new_grep PATTERN [FILE...]\n");
}

int main(int argc, char *argv[]) {
    int first_operand_idx = 1;

    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--") == 0) {
            first_operand_idx = i + 1;
            break;
        }
        if (argv[i][0] == '-' && strcmp(argv[i], "-") != 0) {
            usage();
            return 2;
        }
    }

    if (first_operand_idx >= argc) {
        usage();
        return 2;
    }

    const char *pattern = argv[first_operand_idx];
    size_t pat_len = strlen(pattern);

    int num_files = argc - first_operand_idx - 1;

    int prefix_filename = (num_files > 1) ? 1 : 0;

    int matched_at_least_once = 0;
    int error_occurred = 0;

    if (num_files == 0) {
        while (1) {
            size_t line_len;
            char *line = read_line(stdin, &line_len);
            if (!line && ferror(stdin)) {
                fprintf(stderr, "stdin: %s\n", strerror(errno));
                error_occurred = 1;
                break;
            }
            if (!line) break;

            if (matches(line, line_len, pattern, pat_len)) {
                matched_at_least_once = 1;
                if (write_line(line, line_len) < 0) {
                    error_occurred = 1;
                    break;
                }
            }
            free(line);
        }
    } else {
        for (int i = first_operand_idx + 1; i < argc; i++) {
            int result = search_file(argv[i], pattern, pat_len, prefix_filename);
            if (result == 0) matched_at_least_once = 1;
            if (result == 2) error_occurred = 1;
        }
    }

    if (error_occurred) return 2;
    return matched_at_least_once ? 0 : 1;
}
