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
    return memmem(line, line_len, pattern, pat_len) != NULL;
}

static int write_line_with_prefix(const char *filename, const char *line, size_t len) {
    FILE *out = stdout;
    size_t written = 0;
    size_t prefix_len = strlen(filename);

    while (written < prefix_len) {
        size_t n = fwrite(filename + written, 1, prefix_len - written, out);
        if (n == 0) return -1;
        written += n;
    }

    if (fputc(':', out) == EOF) return -1;

    size_t pos = 0;
    while (pos < len) {
        size_t n = fwrite(line + pos, 1, len - pos, out);
        if (n == 0) return -1;
        pos += n;
    }

    if (fputc('\n', out) == EOF) return -1;

    return 0;
}

static int write_line(const char *line, size_t len) {
    FILE *out = stdout;
    size_t pos = 0;
    while (pos < len) {
        size_t n = fwrite(line + pos, 1, len - pos, out);
        if (n == 0) return -1;
        pos += n;
    }
    if (fputc('\n', out) == EOF) return -1;
    return 0;
}

static int search_file(const char *filename, const char *pattern, size_t pat_len,
                       int prefix_filename) {
    FILE *fp = fopen(filename, "rb");
    if (!fp) {
        fprintf(stderr, "%s: %s\n", filename, strerror(errno));
        return -1;
    }

    int matched_at_least_once = 0;
    size_t line_len;
    char *line;

    while ((line = read_line(fp, &line_len)) != NULL) {
        if (matches(line, line_len, pattern, pat_len)) {
            matched_at_least_once = 1;
            int rc;
            if (prefix_filename) {
                rc = write_line_with_prefix(filename, line, line_len);
            } else {
                rc = write_line(line, line_len);
            }
            if (rc < 0) {
                fprintf(stderr, "write error\n");
                free(line);
                fclose(fp);
                return -2;
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
    if (argc < 2) {
        fprintf(stderr, "Usage: new_grep PATTERN [FILE...]\n");
        return 2;
    }

    int seen_double_dash = 0;
    for (int i = 1; i < argc; i++) {
        const char *arg = argv[i];

        if (strcmp(arg, "--") == 0) {
            seen_double_dash = 1;
            continue;
        }
        if (!seen_double_dash && arg[0] == '-' && strlen(arg) > 1) {
            fprintf(stderr, "unknown option: %s\n", arg);
            return 2;
        }
    }

    int pattern_index = seen_double_dash ? 2 : 1;
    const char *pattern = argv[pattern_index];
    size_t pat_len = strlen(pattern);

    int has_file_args = argc > pattern_index + 1;

    int prefix_filename = (has_file_args && argc > pattern_index + 2) ? 1 : 0;

    if (!has_file_args) {
        size_t line_len;
        char *line;
        int found_match = 0;
        while ((line = read_line(stdin, &line_len)) != NULL) {
            if (matches(line, line_len, pattern, pat_len)) {
                found_match = 1;
                int rc = write_line(line, line_len);
                free(line);
                if (rc < 0) {
                    fprintf(stderr, "write error\n");
                    return 2;
                }
            } else {
                free(line);
            }
        }
        return found_match ? 0 : 1;
    }

    int found_match = 0;
    int has_error = 0;

    int file_start_index = pattern_index + 1;
    for (int i = file_start_index; i < argc; i++) {
        const char *arg = argv[i];

        if (strcmp(arg, "--") == 0) {
            continue;
        }
        if (!seen_double_dash && arg[0] == '-' && strlen(arg) > 1) {
            continue;
        }

        if (is_directory(arg)) {
            fprintf(stderr, "%s: is a directory\n", arg);
            has_error = 1;
            continue;
        }

        int rc = search_file(arg, pattern, pat_len, prefix_filename);
        if (rc == -2) return 2;
        if (rc == 0) found_match = 1;
        if (rc < 0) has_error = 1;
    }

    if (has_error) return 2;
    return found_match ? 0 : 1;
}
