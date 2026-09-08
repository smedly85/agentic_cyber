#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <sys/stat.h>

static void oom(void) {
    fprintf(stderr, "new_grep: out of memory\n");
    exit(2);
}

static void *xrealloc(void *p, size_t n) {
    if (n == 0) { free(p); return NULL; }
    void *q = realloc(p, n);
    if (!q) oom();
    return q;
}

static int bytes_contains(const unsigned char *hay, size_t hlen,
                          const unsigned char *needle, size_t nlen) {
    if (nlen == 0) return 1;
    if (nlen > hlen) return 0;
    for (size_t i = 0; i <= hlen - nlen; i++) {
        if (memcmp(hay + i, needle, nlen) == 0) return 1;
    }
    return 0;
}

static int write_selected(const unsigned char *line, size_t len,
                          const char *prefix) {
    if (prefix) {
        size_t plen = strlen(prefix);
        if (fwrite(prefix, 1, plen, stdout) != plen) return -1;
        if (fputc(':', stdout) == EOF) return -1;
    }
    if (len > 0) {
        if (fwrite(line, 1, len, stdout) != len) return -1;
    }
    if (fputc('\n', stdout) == EOF) return -1;
    return 0;
}

static int process_fd(int fd,
                      const unsigned char *pattern, size_t pattern_len,
                      const char *prefix,
                      int *found) {
    enum { RBUF_SIZE = 8192 };
    unsigned char *rbuf = malloc(RBUF_SIZE);
    if (!rbuf) oom();

    unsigned char *line = NULL;
    size_t line_len = 0, line_cap = 0;
    size_t rpos = 0, rlen = 0;
    int eof = 0;

    while (!eof) {
        if (rpos >= rlen) {
            ssize_t n;
            do { n = read(fd, rbuf, RBUF_SIZE); } while (n < 0 && errno == EINTR);
            if (n < 0) { free(rbuf); free(line); return -1; }
            if (n == 0) { eof = 1; break; }
            rlen = (size_t)n;
            rpos = 0;
        }

        unsigned char c = rbuf[rpos++];
        if (c == '\n') {
            if (bytes_contains(line, line_len, pattern, pattern_len)) {
                *found = 1;
                if (write_selected(line, line_len, prefix) != 0) {
                    free(rbuf); free(line);
                    return -1;
                }
            }
            line_len = 0;
        } else {
            if (line_len + 1 > line_cap) {
                size_t nc = line_cap ? line_cap * 2 : 256;
                if (nc < line_len + 1) nc = line_len + 1;
                line = xrealloc(line, nc);
                line_cap = nc;
            }
            line[line_len++] = c;
        }
    }

    if (line_len > 0) {
        if (bytes_contains(line, line_len, pattern, pattern_len)) {
            *found = 1;
            if (write_selected(line, line_len, prefix) != 0) {
                free(rbuf); free(line);
                return -1;
            }
        }
    }

    free(rbuf);
    free(line);
    return 0;
}

static int is_unknown_option(const char *arg) {
    return arg[0] == '-' && arg[1] != '\0';
}

int main(int argc, char **argv) {
    if (argc < 2) {
        fprintf(stderr, "usage: new_grep PATTERN [FILE...]\n");
        return 2;
    }

    const char *pattern_str;
    const char **files;
    int nfiles;

    if (strcmp(argv[1], "--") == 0) {
        if (argc < 3) {
            fprintf(stderr, "usage: new_grep PATTERN [FILE...]\n");
            return 2;
        }
        pattern_str = argv[2];
        files = (const char **)&argv[3];
        nfiles = argc - 3;
    } else if (is_unknown_option(argv[1])) {
        fprintf(stderr, "new_grep: unknown option: %s\n", argv[1]);
        return 2;
    } else {
        pattern_str = argv[1];
        files = (const char **)&argv[2];
        nfiles = argc - 2;
        for (int j = 0; j < nfiles; j++) {
            if (is_unknown_option(files[j])) {
                fprintf(stderr, "new_grep: unknown option: %s\n", files[j]);
                return 2;
            }
        }
    }

    const unsigned char *pattern = (const unsigned char *)pattern_str;
    size_t pattern_len = strlen(pattern_str);
    int use_prefix = (nfiles >= 2);

    int any_match = 0;
    int any_error = 0;

    if (nfiles == 0) {
        int found = 0;
        if (process_fd(STDIN_FILENO, pattern, pattern_len, NULL, &found) != 0) {
            if (ferror(stdout))
                fprintf(stderr, "new_grep: write error\n");
            else
                fprintf(stderr, "new_grep: error reading stdin\n");
            return 2;
        }
        any_match = found;
    } else {
        for (int j = 0; j < nfiles; j++) {
            const char *path = files[j];
            struct stat st;
            if (stat(path, &st) != 0) {
                fprintf(stderr, "new_grep: %s: %s\n", path, strerror(errno));
                any_error = 1;
                continue;
            }
            if (S_ISDIR(st.st_mode)) {
                fprintf(stderr, "new_grep: %s: is a directory\n", path);
                any_error = 1;
                continue;
            }
            int fd = open(path, O_RDONLY);
            if (fd < 0) {
                fprintf(stderr, "new_grep: %s: %s\n", path, strerror(errno));
                any_error = 1;
                continue;
            }
            int found = 0;
            int ret = process_fd(fd, pattern, pattern_len,
                                 use_prefix ? path : NULL, &found);
            close(fd);
            if (ret != 0) {
                if (ferror(stdout))
                    fprintf(stderr, "new_grep: write error\n");
                else
                    fprintf(stderr, "new_grep: %s: read error\n", path);
                return 2;
            }
            if (found) any_match = 1;
        }
    }

    if (fflush(stdout) != 0) {
        fprintf(stderr, "new_grep: write error\n");
        return 2;
    }

    if (any_error) return 2;
    if (any_match) return 0;
    return 1;
}
