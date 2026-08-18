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
                buf[len] = '\0';
                *len_out = len;
                return buf;
            }
            free(buf);
            *len_out = 0;
            return NULL;
        }
        if (c == '\n') {
            buf[len] = '\0';
            *len_out = len;
            return buf;
        }
        buf[len++] = (char)c;
        if (len >= capacity) {
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
    }
}

static int contains_pattern(const char *line, size_t line_len,
                            const char *pattern, size_t pattern_len) {
    if (pattern_len == 0) return 1;
    if (pattern_len > line_len) return 0;
    for (size_t i = 0; i <= line_len - pattern_len; i++) {
        if (memcmp(line + i, pattern, pattern_len) == 0) {
            return 1;
        }
    }
    return 0;
}

static int search_file(const char *filename, const char *pattern, size_t pattern_len,
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
    size_t line_len;
    char *line;

    while ((line = read_line(fp, &line_len)) != NULL) {
        if (contains_pattern(line, line_len, pattern, pattern_len)) {
            if (prefix_filename) {
                if (fprintf(stdout, "%s:", filename) < 0) {
                    error_occurred = 1;
                    break;
                }
            }
            if (line_len > 0) {
                if (fwrite(line, 1, line_len, stdout) != line_len) {
                    error_occurred = 1;
                    break;
                }
            }
            if (putc('\n', stdout) == EOF) {
                error_occurred = 1;
                break;
            }
            matched = 1;
        }
        free(line);
    }

    fclose(fp);

    if (error_occurred) {
        fprintf(stderr, "write error\n");
        return 2;
    }

    return matched ? 0 : 1;
}

static void usage(void) {
    fprintf(stderr, "usage: new_grep [-H] [--with-filename] PATTERN [FILE...]\n");
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        usage();
        return 2;
    }

    int found_double_dash_at = -1;
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--") == 0) {
            found_double_dash_at = i;
            break;
        }
    }

    int force_filename = 0;
    int options_end = (found_double_dash_at >= 0 ? found_double_dash_at : argc);

    for (int i = 1; i < options_end; i++) {
        if (strcmp(argv[i], "-H") == 0 || strcmp(argv[i], "--with-filename") == 0) {
            force_filename = 1;
        } else if (argv[i][0] == '-' && strlen(argv[i]) > 1) {
            usage();
            return 2;
        }
    }

    int pattern_index;
    if (found_double_dash_at >= 0 && found_double_dash_at + 1 < argc) {
        pattern_index = found_double_dash_at + 1;
    } else {
        for (pattern_index = 1; pattern_index < options_end; pattern_index++) {
            if (strcmp(argv[pattern_index], "-H") != 0 &&
                strcmp(argv[pattern_index], "--with-filename") != 0) {
                break;
            }
        }
    }

    const char *pattern = argv[pattern_index];
    size_t pattern_len = strlen(pattern);

    int file_offset;
    if (found_double_dash_at >= 0) {
        file_offset = found_double_dash_at + 2;
    } else {
        file_offset = pattern_index + 1;
    }

    int file_count = argc - file_offset;

    int prefix_filename = (force_filename || file_count >= 2);

    if (file_count == 0) {
        size_t line_len;
        char *line;
        int matched = 0;

        while ((line = read_line(stdin, &line_len)) != NULL) {
            if (contains_pattern(line, line_len, pattern, pattern_len)) {
                if (prefix_filename) {
                    if (fprintf(stdout, "(standard input):") < 0) {
                        fprintf(stderr, "write error\n");
                        return 2;
                    }
                }
                if (line_len > 0) {
                    if (fwrite(line, 1, line_len, stdout) != line_len) {
                        fprintf(stderr, "write error\n");
                        return 2;
                    }
                }
                if (putc('\n', stdout) == EOF) {
                    fprintf(stderr, "write error\n");
                    return 2;
                }
                matched = 1;
            }
            free(line);
        }

        return matched ? 0 : 1;
    } else {
        int status = 0;
        int matched_any = 0;

        for (int i = file_offset; i < argc; i++) {
            if (strcmp(argv[i], "--") == 0) continue;
            if (argv[i][0] == '-' && strlen(argv[i]) > 1) continue;
            int result = search_file(argv[i], pattern, pattern_len, prefix_filename);
            if (result == 2) status = 2;
            else if (result == 0) matched_any = 1;
        }

        return status != 0 ? 2 : (matched_any ? 0 : 1);
    }
}
