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
            if (len == 0) {
                free(buf);
                return NULL;
            }
            break;
        }
        if (c == '\n') {
            break;
        }
        if (len >= capacity - 1) {
            size_t new_cap = capacity * 2;
            if (new_cap < capacity || new_cap > SIZE_MAX / 2) {
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

    if (len >= capacity - 1) {
        char *new_buf = realloc(buf, len + 2);
        if (!new_buf) {
            free(buf);
            return NULL;
        }
        buf = new_buf;
    }
    buf[len] = '\0';
    *len_out = len;
    return buf;
}

static int matches(const char *line, size_t line_len, const char *pattern, size_t pat_len) {
    if (pat_len == 0) return 1;
    if (pat_len > line_len) return 0;
    for (size_t i = 0; i <= line_len - pat_len; i++) {
        if (memcmp(line + i, pattern, pat_len) == 0) {
            return 1;
        }
    }
    return 0;
}

static int search_file(const char *filename, const char *pattern, size_t pat_len,
                       int prefix_filename, int *error_occurred) {
    FILE *fp = fopen(filename, "rb");
    if (!fp) {
        fprintf(stderr, "%s: %s\n", filename, strerror(errno));
        *error_occurred = 1;
        return 0;
    }

    struct stat st;
    if (fstat(fileno(fp), &st) == 0 && S_ISDIR(st.st_mode)) {
        fprintf(stderr, "%s: Is a directory\n", filename);
        fclose(fp);
        *error_occurred = 1;
        return 0;
    }

    int matched_at_least_once = 0;
    size_t line_len;
    char *line;

    while ((line = read_line(fp, &line_len)) != NULL) {
        if (matches(line, line_len, pattern, pat_len)) {
            if (prefix_filename) {
                fprintf(stdout, "%s:", filename);
            }
            if (line_len > 0) {
                fwrite(line, 1, line_len, stdout);
            }
            fputc('\n', stdout);
            matched_at_least_once = 1;
        }
        free(line);
    }

    fclose(fp);
    return matched_at_least_once;
}

static void usage(const char *prog) {
    fprintf(stderr, "Usage: %s PATTERN [FILE...]\n", prog);
}

static int filename_prefix_state = 0;

int main(int argc, char *argv[]) {
    if (argc < 2) {
        usage(argv[0]);
        return 2;
    }

    const char *pattern = NULL;
    int file_start_idx = -1;

    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--") == 0) {
            file_start_idx = i + 1;
            break;
        } else if (argv[i][0] == '-' && strlen(argv[i]) > 1) {
            const char *arg = argv[i];
            if (strcmp(arg, "-H") == 0 || strcmp(arg, "--with-filename") == 0) {
                filename_prefix_state = 1;
            } else if (strcmp(arg, "-h") == 0 || strcmp(arg, "--no-filename") == 0) {
                filename_prefix_state = -1;
            } else if (arg[1] != '\0') {
                for (int j = 1; arg[j]; j++) {
                    if (arg[j] == 'H') {
                        filename_prefix_state = 1;
                    } else if (arg[j] == 'h') {
                        filename_prefix_state = -1;
                    } else {
                        fprintf(stderr, "Unknown option: %s\n", argv[i]);
                        return 2;
                    }
                }
            } else {
                fprintf(stderr, "Unknown option: %s\n", argv[i]);
                return 2;
            }
        }
    }

    int pattern_idx = 1;
    if (file_start_idx >= 0) {
        pattern_idx = file_start_idx;
    } else {
        while (pattern_idx < argc && argv[pattern_idx][0] == '-' && strlen(argv[pattern_idx]) > 1) {
            pattern_idx++;
        }
    }
    pattern = argv[pattern_idx];

    if (!pattern) {
        usage(argv[0]);
        return 2;
    }

    size_t pat_len = strlen(pattern);

    int file_count = (file_start_idx >= 0 && file_start_idx + 1 < argc) ? (argc - file_start_idx - 1) : (argc - pattern_idx - 1);
    int prefix_filename = (filename_prefix_state == 1) || (filename_prefix_state != -1 && file_count > 1);

    int matched_at_least_once = 0;
    int error_occurred = 0;

    if (file_count == 0) {
        size_t line_len;
        char *line;
        while ((line = read_line(stdin, &line_len)) != NULL) {
            if (matches(line, line_len, pattern, pat_len)) {
                if (prefix_filename) {
                    fprintf(stdout, "(standard input):");
                }
                if (line_len > 0) {
                    fwrite(line, 1, line_len, stdout);
                }
                fputc('\n', stdout);
                matched_at_least_once = 1;
            }
            free(line);
        }
    } else {
        int file_start = pattern_idx + 1;
        for (int i = file_start; i < argc; i++) {
            int m = search_file(argv[i], pattern, pat_len, prefix_filename, &error_occurred);
            if (m) matched_at_least_once = 1;
        }
    }

    if (error_occurred) return 2;
    return matched_at_least_once ? 0 : 1;
}
