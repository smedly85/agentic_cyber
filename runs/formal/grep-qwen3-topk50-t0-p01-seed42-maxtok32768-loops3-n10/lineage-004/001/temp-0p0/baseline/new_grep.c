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

    int matched_at_least_once = 0;

    while (1) {
        size_t line_len;
        char *line = read_line(fp, &line_len);
        if (!line && errno != 0) {
            fprintf(stderr, "%s: %s\n", filename, strerror(errno));
            fclose(fp);
            return 2;
        }
        if (!line) break;

        if (matches(line, line_len, pattern, pat_len)) {
            matched_at_least_once = 1;
            if (prefix_filename) {
                if (write_line_with_prefix(filename, line, line_len) < 0) {
                    perror("new_grep");
                    free(line);
                    fclose(fp);
                    return 2;
                }
            } else {
                if (write_line(line, line_len) < 0) {
                    perror("new_grep");
                    free(line);
                    fclose(fp);
                    return 2;
                }
            }
        }
        free(line);
    }

    fclose(fp);
    return matched_at_least_once ? 0 : 1;
}

static int is_directory(const char *path) {
    struct stat st;
    if (stat(path, &st) != 0) return 0;
    return S_ISDIR(st.st_mode);
}

int main(int argc, char *argv[]) {
    int separator_idx = -1;
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--") == 0) {
            separator_idx = i;
            break;
        }
    }

    int first_operand_idx = (separator_idx >= 0) ? separator_idx + 1 : 1;

    if (first_operand_idx >= argc) {
        fprintf(stderr, "Usage: new_grep PATTERN [FILE...]\n");
        return 2;
    }

    const char *pattern = argv[first_operand_idx];
    size_t pat_len = strlen(pattern);

    int file_count = argc - first_operand_idx - 1;
    int prefix_filename = (file_count >= 2) ? 1 : 0;

    if (file_count == 0) {
        int matched_at_least_once = 0;

        while (1) {
            size_t line_len;
            char *line = read_line(stdin, &line_len);
            if (!line && errno != 0) {
                perror("new_grep");
                return 2;
            }
            if (!line) break;

            if (matches(line, line_len, pattern, pat_len)) {
                matched_at_least_once = 1;
                if (write_line(line, line_len) < 0) {
                    perror("new_grep");
                    free(line);
                    return 2;
                }
            }
            free(line);
        }

        return matched_at_least_once ? 0 : 1;
    } else {
        int error_occurred = 0;
        int matched_anywhere = 0;
        int start_idx = first_operand_idx + 1;

        for (int i = start_idx; i < argc; i++) {
            const char *filename = argv[i];

            if (is_directory(filename)) {
                fprintf(stderr, "%s: Is a directory\n", filename);
                error_occurred = 1;
                continue;
            }

            int file_status = search_file(filename, pattern, pat_len, prefix_filename);
            if (file_status == 2) {
                error_occurred = 1;
            } else if (file_status == 0) {
                matched_anywhere = 1;
            }
        }

        return error_occurred ? 2 : (matched_anywhere ? 0 : 1);
    }
}
