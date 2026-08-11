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

static int contains_pattern(const char *line, size_t line_len, const char *pattern, size_t pat_len) {
    if (pat_len == 0) return 1;
    if (pat_len > line_len) return 0;
    for (size_t i = 0; i <= line_len - pat_len; i++) {
        if (memcmp(line + i, pattern, pat_len) == 0) {
            return 1;
        }
    }
    return 0;
}

static int search_file(const char *filename, const char *pattern, size_t pat_len, int prefix_filename) {
    FILE *fp = fopen(filename, "rb");
    if (!fp) {
        fprintf(stderr, "new_grep: cannot open '%s': %s\n", filename, strerror(errno));
        return 2;
    }

    struct stat st;
    if (fstat(fileno(fp), &st) == 0 && S_ISDIR(st.st_mode)) {
        fprintf(stderr, "new_grep: '%s' is a directory\n", filename);
        fclose(fp);
        return 2;
    }

    int matched = 0;
    int error_occurred = 0;
    size_t len;
    char *line;

    while ((line = read_line(fp, &len)) != NULL) {
        if (contains_pattern(line, len, pattern, pat_len)) {
            if (prefix_filename) {
                if (fprintf(stdout, "%s:", filename) < 0) {
                    error_occurred = 1;
                    break;
                }
            }
            if (len > 0) {
                if (fwrite(line, 1, len, stdout) != len) {
                    error_occurred = 1;
                    free(line);
                    break;
                }
            }
            if (putc('\n', stdout) == EOF) {
                error_occurred = 1;
                free(line);
                break;
            }
            matched = 1;
        }
        free(line);
    }

    fclose(fp);

    if (error_occurred) {
        fprintf(stderr, "new_grep: write error\n");
        return 2;
    }

    return matched ? 0 : 1;
}

static void usage(void) {
    fprintf(stderr, "usage: new_grep [-H|-h] PATTERN [FILE...]\n");
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        usage();
        return 2;
    }

    int arg_idx = 1;
    int filename_mode = 0;

    while (arg_idx < argc) {
        if (strcmp(argv[arg_idx], "--") == 0) {
            arg_idx++;
            break;
        }
        if (argv[arg_idx][0] == '-' && argv[arg_idx][1] != '\0') {
            if (strcmp(argv[arg_idx], "-H") == 0 || strcmp(argv[arg_idx], "--with-filename") == 0) {
                filename_mode = 1;
                arg_idx++;
                continue;
            }
            if (strcmp(argv[arg_idx], "-h") == 0 || strcmp(argv[arg_idx], "--no-filename") == 0) {
                filename_mode = -1;
                arg_idx++;
                continue;
            }
            for (int i = 1; argv[arg_idx][i] != '\0'; i++) {
                char c = argv[arg_idx][i];
                if (c == 'H') {
                    filename_mode = 1;
                } else if (c == 'h') {
                    filename_mode = -1;
                } else {
                    usage();
                    return 2;
                }
            }
            arg_idx++;
            continue;
        }
        break;
    }

    if (arg_idx >= argc) {
        usage();
        return 2;
    }

    const char *pattern = argv[arg_idx];
    size_t pat_len = strlen(pattern);

    int file_count = argc - arg_idx - 1;
    int prefix_filename = filename_mode == 1 || (filename_mode != -1 && file_count > 1);

    if (file_count == 0) {
        size_t len;
        char *line;
        int matched = 0;
        while ((line = read_line(stdin, &len)) != NULL) {
            if (contains_pattern(line, len, pattern, pat_len)) {
                if (prefix_filename) {
                    if (fprintf(stdout, "(standard input):") < 0) {
                        fprintf(stderr, "new_grep: write error\n");
                        free(line);
                        return 2;
                    }
                }
                if (len > 0) {
                    if (fwrite(line, 1, len, stdout) != len) {
                        fprintf(stderr, "new_grep: write error\n");
                        free(line);
                        return 2;
                    }
                }
                if (putc('\n', stdout) == EOF) {
                    fprintf(stderr, "new_grep: write error\n");
                    free(line);
                    return 2;
                }
                matched = 1;
            }
            free(line);
        }
        return matched ? 0 : 1;
    }

    int exit_status = 1;
    for (int i = 0; i < file_count; i++) {
        const char *filename = argv[arg_idx + 1 + i];
        int status = search_file(filename, pattern, pat_len, prefix_filename);
        if (status == 2) {
            exit_status = 2;
        } else if (status == 0 && exit_status != 2) {
            exit_status = 0;
        }
    }

    return exit_status;
}
