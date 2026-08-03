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

static int search_file(const char *filename, const char *pattern, size_t pat_len, int prefix_filename) {
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
    size_t len;
    char *line;

    while ((line = read_line(fp, &len)) != NULL) {
        if (matches(line, len, pattern, pat_len)) {
            if (prefix_filename) {
                if (fprintf(stdout, "%s:", filename) < 0) {
                    error_occurred = 1;
                    free(line);
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

    if (ferror(fp)) {
        fprintf(stderr, "%s: %s\n", filename, strerror(errno));
        error_occurred = 1;
    }

    fclose(fp);
    return error_occurred ? 2 : (matched ? 0 : 1);
}

static void usage(void) {
    fprintf(stderr, "Usage: new_grep PATTERN [FILE...]\n");
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        usage();
        return 2;
    }

    int i = 1;
    while (i < argc && argv[i][0] == '-' && strcmp(argv[i], "--") != 0) {
        if (strcmp(argv[i], "-") == 0) {
            break;
        }
        fprintf(stderr, "unknown option: %s\n", argv[i]);
        return 2;
    }

    if (i < argc && strcmp(argv[i], "--") == 0) {
        i++;
    }

    const char *pattern = argv[i++];
    size_t pat_len = strlen(pattern);

    int file_count = argc - i;
    int prefix_filename = file_count > 1;

    if (file_count == 0) {
        int matched = 0;
        int error_occurred = 0;
        size_t len;
        char *line;

        while ((line = read_line(stdin, &len)) != NULL) {
            if (matches(line, len, pattern, pat_len)) {
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

        if (ferror(stdin)) {
            fprintf(stderr, "stdin: %s\n", strerror(errno));
            error_occurred = 1;
        }

        return error_occurred ? 2 : (matched ? 0 : 1);
    } else {
        int exit_status = 0;
        int matched_at_least_once = 0;
        for (; i < argc; i++) {
            int status = search_file(argv[i], pattern, pat_len, prefix_filename);
            if (status == 2) {
                exit_status = 2;
            } else if (status == 0) {
                matched_at_least_once = 1;
            }
        }
        if (exit_status != 2) {
            exit_status = matched_at_least_once ? 0 : 1;
        }
        return exit_status;
    }
}
