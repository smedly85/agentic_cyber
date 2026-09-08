#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <errno.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

#define READ_CHUNK 8192

static void fail_oom(void) {
    fprintf(stderr, "new_grep: out of memory\n");
    exit(2);
}

static void *xrealloc(void *p, size_t n) {
    void *r = realloc(p, n);
    if (!r) fail_oom();
    return r;
}

static int contains_pattern(const unsigned char *hay, size_t hay_len,
                            const unsigned char *pat, size_t pat_len) {
    if (pat_len == 0) return 1;
    if (pat_len > hay_len) return 0;
    for (size_t i = 0; i <= hay_len - pat_len; i++) {
        if (memcmp(hay + i, pat, pat_len) == 0) return 1;
    }
    return 0;
}

static int write_output(const char *prefix, const unsigned char *line, size_t line_len) {
    if (prefix) {
        size_t plen = strlen(prefix);
        if (fwrite(prefix, 1, plen, stdout) != plen) return -1;
        if (fputc(':', stdout) == EOF) return -1;
    }
    if (line_len > 0) {
        if (fwrite(line, 1, line_len, stdout) != line_len) return -1;
    }
    if (fputc('\n', stdout) == EOF) return -1;
    return 0;
}

static int search_fd(int fd, const unsigned char *pat, size_t pat_len,
                     const char *prefix, int *found) {
    unsigned char *chunk = NULL;
    unsigned char *line = NULL;
    size_t line_len = 0, line_cap = 0;
    size_t cpos = 0, clen = 0;
    int rc = 0;

    chunk = xrealloc(NULL, READ_CHUNK);

    for (;;) {
        if (cpos >= clen) {
            ssize_t n;
            do {
                n = read(fd, chunk, READ_CHUNK);
            } while (n < 0 && errno == EINTR);
            if (n < 0) { rc = -1; goto done; }
            if (n == 0) {
                if (line_len > 0) {
                    if (contains_pattern(line, line_len, pat, pat_len)) {
                        if (write_output(prefix, line, line_len) != 0) { rc = -1; goto done; }
                        *found = 1;
                    }
                }
                break;
            }
            clen = (size_t)n;
            cpos = 0;
        }

        unsigned char b = chunk[cpos++];
        if (b == '\n') {
            if (contains_pattern(line, line_len, pat, pat_len)) {
                if (write_output(prefix, line, line_len) != 0) { rc = -1; goto done; }
                *found = 1;
            }
            line_len = 0;
        } else {
            if (line_len + 1 > line_cap) {
                size_t ncap = line_cap ? line_cap * 2 : 256;
                if (ncap < line_len + 1) ncap = line_len + 1;
                line = xrealloc(line, ncap);
                line_cap = ncap;
            }
            line[line_len++] = b;
        }
    }

done:
    free(chunk);
    free(line);
    return rc;
}

static void usage(void) {
    fprintf(stderr, "usage: new_grep PATTERN [FILE...]\n");
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        usage();
        return 2;
    }

    int saw_terminator = 0;
    int prefix_mode = -1;
    int pattern_idx = -1;
    char **file_args = NULL;
    int file_count = 0;

    for (int i = 1; i < argc; i++) {
        const char *arg = argv[i];

        if (!saw_terminator) {
            if (strcmp(arg, "--") == 0) {
                saw_terminator = 1;
                continue;
            }
            if (arg[0] == '-' && arg[1] != '\0') {
                if (arg[1] == '-') {
                    if (strcmp(arg, "--with-filename") == 0) {
                        prefix_mode = 1;
                    } else if (strcmp(arg, "--no-filename") == 0) {
                        prefix_mode = 0;
                    } else {
                        usage();
                        return 2;
                    }
                    continue;
                }
                for (const char *c = arg + 1; *c; c++) {
                    if (*c == 'H') {
                        prefix_mode = 1;
                    } else if (*c == 'h') {
                        prefix_mode = 0;
                    } else {
                        usage();
                        return 2;
                    }
                }
                continue;
            }
        }

        if (pattern_idx == -1) {
            pattern_idx = i;
        } else {
            file_args = xrealloc(file_args, (size_t)(file_count + 1) * sizeof(char *));
            file_args[file_count++] = (char *)arg;
        }
    }

    if (pattern_idx == -1) {
        usage();
        return 2;
    }

    const char *pattern = argv[pattern_idx];
    size_t pattern_len = strlen(pattern);
    int use_prefix;
    if (prefix_mode == 1)
        use_prefix = 1;
    else if (prefix_mode == 0)
        use_prefix = 0;
    else
        use_prefix = (file_count >= 2) ? 1 : 0;
    int any_found = 0;
    int had_error = 0;

    if (file_count == 0) {
        const char *stdin_prefix = use_prefix ? "(standard input)" : NULL;
        if (search_fd(0, (const unsigned char *)pattern, pattern_len, stdin_prefix, &any_found) != 0)
            had_error = 1;
    } else {
        for (int i = 0; i < file_count; i++) {
            const char *path = file_args[i];

            struct stat st;
            if (stat(path, &st) != 0) {
                fprintf(stderr, "new_grep: %s: %s\n", path, strerror(errno));
                had_error = 1;
                continue;
            }
            if (S_ISDIR(st.st_mode)) {
                fprintf(stderr, "new_grep: %s: is a directory\n", path);
                had_error = 1;
                continue;
            }

            int fd = open(path, O_RDONLY);
            if (fd < 0) {
                fprintf(stderr, "new_grep: %s: %s\n", path, strerror(errno));
                had_error = 1;
                continue;
            }

            const char *prefix = use_prefix ? path : NULL;
            if (search_fd(fd, (const unsigned char *)pattern, pattern_len, prefix, &any_found) != 0)
                had_error = 1;
            close(fd);
        }
    }

    free(file_args);

    if (had_error) return 2;
    return any_found ? 0 : 1;
}
