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

    int got_data = 0;
    while (1) {
        int c = fgetc(fp);
        if (c == EOF) {
            if (got_data) break;
            free(buf);
            return NULL;
        }
        if (c == '\n') {
            break;
        }
        got_data = 1;
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
        return -1;
    }

    int matched_at_least_once = 0;

    while (1) {
        size_t line_len;
        char *line = read_line(fp, &line_len);
        if (!line && errno != 0) {
            fprintf(stderr, "%s: %s\n", filename, strerror(errno));
            fclose(fp);
            return -1;
        }
        if (!line) break;

        if (matches(line, line_len, pattern, pat_len)) {
            matched_at_least_once = 1;
            int rc;
            if (prefix_filename) {
                rc = write_line_with_prefix(filename, line, line_len);
            } else {
                rc = write_line(line, line_len);
            }
            if (rc < 0) {
                fprintf(stderr, "write error: %s\n", strerror(errno));
                free(line);
                fclose(fp);
                return -1;
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
    const char *pattern = NULL;
    const char **filenames = NULL;
    int file_count = 0;
    int force_filename = 0;

    int i = 1;
    while (i < argc) {
        if (strcmp(argv[i], "--") == 0) {
            i++;
            break;
        }
        if (argv[i][0] == '-' && strlen(argv[i]) > 1) {
            if (strcmp(argv[i], "-H") == 0 || strcmp(argv[i], "--with-filename") == 0) {
                force_filename = 1;
                i++;
            } else if (strcmp(argv[i], "-h") == 0 || strcmp(argv[i], "--no-filename") == 0) {
                force_filename = -1;
                i++;
            } else if (argv[i][1] == 'H' && strlen(argv[i]) == 2) {
                force_filename = 1;
                i++;
            } else if (argv[i][1] == 'h' && strlen(argv[i]) == 2) {
                force_filename = -1;
                i++;
            } else if (strlen(argv[i]) > 2 && argv[i][0] == '-' && argv[i][1] != '-') {
                for (size_t k = 1; k < strlen(argv[i]); k++) {
                    if (argv[i][k] == 'H') {
                        force_filename = 1;
                    } else if (argv[i][k] == 'h') {
                        force_filename = -1;
                    } else {
                        fprintf(stderr, "usage: new_grep PATTERN [FILE...]\n");
                        return 2;
                    }
                }
                i++;
            } else {
                fprintf(stderr, "usage: new_grep PATTERN [FILE...]\n");
                return 2;
            }
        } else {
            break;
        }
    }

    if (i >= argc) {
        fprintf(stderr, "usage: new_grep PATTERN [FILE...]\n");
        return 2;
    }

    pattern = argv[i];
    i++;

    for (int j = i; j < argc; j++) {
        filenames = realloc(filenames, (file_count + 1) * sizeof(char *));
        if (!filenames) {
            fprintf(stderr, "memory allocation failed\n");
            return 2;
        }
        filenames[file_count++] = argv[j];
    }

    size_t pat_len = strlen(pattern);

    int use_prefix = (force_filename == 1) ? 1 : ((file_count >= 2 && force_filename != -1) ? 1 : 0);

    int exit_status = 0;
    int matched_at_least_once = 0;

    if (file_count == 0) {
        while (1) {
            size_t line_len;
            char *line = read_line(stdin, &line_len);
            if (!line) break;

            if (matches(line, line_len, pattern, pat_len)) {
                matched_at_least_once = 1;
                int rc;
                if (force_filename == 1) {
                    rc = write_line_with_prefix("(standard input)", line, line_len);
                } else {
                    rc = write_line(line, line_len);
                }
                if (rc < 0) {
                    fprintf(stderr, "write error: %s\n", strerror(errno));
                    free(line);
                    free(filenames);
                    return 2;
                }
            }
            free(line);
        }
    } else {
        for (int j = 0; j < file_count; j++) {
            const char *fname = filenames[j];

            if (is_directory(fname)) {
                fprintf(stderr, "%s: Is a directory\n", fname);
                exit_status = 2;
                continue;
            }

            int result = search_file(fname, pattern, pat_len, use_prefix);
            if (result < 0) {
                exit_status = 2;
            } else if (result == 0) {
                matched_at_least_once = 1;
            }
        }
    }

    free(filenames);

    if (exit_status != 0) return 2;
    return matched_at_least_once ? 0 : 1;
}
