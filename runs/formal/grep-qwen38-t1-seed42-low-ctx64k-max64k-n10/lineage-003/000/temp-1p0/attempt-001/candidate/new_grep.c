#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdbool.h>
#include <errno.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/stat.h>

#define INBUF_SIZE 8192

typedef struct {
    int fd;
    unsigned char buf[INBUF_SIZE];
    size_t pos;
    size_t len;
} inbuf_t;

static int inbuf_get(inbuf_t *ib, unsigned char *c) {
    if (ib->pos >= ib->len) {
        ssize_t n = read(ib->fd, ib->buf, sizeof(ib->buf));
        if (n < 0) return -1;
        if (n == 0) return 0;
        ib->len = (size_t)n;
        ib->pos = 0;
    }
    *c = ib->buf[ib->pos++];
    return 1;
}

typedef struct {
    unsigned char *data;
    size_t len;
    size_t cap;
} linebuf_t;

static int linebuf_push(linebuf_t *lb, unsigned char c) {
    if (lb->len + 1 > lb->cap) {
        size_t ncap = lb->cap ? lb->cap * 2 : 256;
        unsigned char *nd = realloc(lb->data, ncap);
        if (!nd) return -1;
        lb->data = nd;
        lb->cap = ncap;
    }
    lb->data[lb->len++] = c;
    return 0;
}

static int pattern_match(const unsigned char *line, size_t line_len,
                         const unsigned char *pat, size_t pat_len) {
    if (pat_len == 0) return 1;
    if (pat_len > line_len) return 0;
    for (size_t i = 0; i <= line_len - pat_len; i++) {
        if (memcmp(line + i, pat, pat_len) == 0) return 1;
    }
    return 0;
}

static int emit_line(const unsigned char *line, size_t len,
                     bool prefix, const char *name) {
    if (prefix && name) {
        size_t nlen = strlen(name);
        if (nlen > 0 && write(STDOUT_FILENO, name, nlen) != (ssize_t)nlen)
            return -1;
        if (write(STDOUT_FILENO, ":", 1) != 1) return -1;
    }
    if (len > 0 && write(STDOUT_FILENO, line, len) != (ssize_t)len)
        return -1;
    if (write(STDOUT_FILENO, "\n", 1) != 1) return -1;
    return 0;
}

static int search_stream(inbuf_t *ib, const unsigned char *pat, size_t pat_len,
                         bool prefix, const char *name) {
    int found = 0;
    linebuf_t lb = {0};
    int rc = 0;

    for (;;) {
        unsigned char c;
        int r = inbuf_get(ib, &c);
        if (r < 0) { rc = -1; break; }
        if (r == 0) {
            if (lb.len > 0) {
                if (pattern_match(lb.data, lb.len, pat, pat_len)) {
                    if (emit_line(lb.data, lb.len, prefix, name) < 0) { rc = -1; break; }
                    found = 1;
                }
            }
            break;
        }
        if (c == '\n') {
            if (pattern_match(lb.data, lb.len, pat, pat_len)) {
                if (emit_line(lb.data, lb.len, prefix, name) < 0) { rc = -1; break; }
                found = 1;
            }
            lb.len = 0;
        } else {
            if (linebuf_push(&lb, c) < 0) { rc = -1; break; }
        }
    }

    free(lb.data);
    if (rc < 0) return -1;
    return found;
}

int main(int argc, char *argv[]) {
    char **operands = NULL;
    int n_op = 0, cap_op = 0;
    int seen_ddash = 0;

    for (int i = 1; i < argc; i++) {
        const char *arg = argv[i];
        char **result;
        if (seen_ddash) {
            if (n_op + 1 > cap_op) {
                int ncap = cap_op ? cap_op * 2 : 4;
                result = realloc(operands, (size_t)ncap * sizeof(char *));
                if (!result) { fprintf(stderr, "new_grep: out of memory\n"); return 2; }
                operands = result;
                cap_op = ncap;
            }
            operands[n_op++] = (char *)arg;
        } else if (strcmp(arg, "--") == 0) {
            seen_ddash = 1;
        } else if (strcmp(arg, "-") == 0) {
            if (n_op + 1 > cap_op) {
                int ncap = cap_op ? cap_op * 2 : 4;
                result = realloc(operands, (size_t)ncap * sizeof(char *));
                if (!result) { fprintf(stderr, "new_grep: out of memory\n"); return 2; }
                operands = result;
                cap_op = ncap;
            }
            operands[n_op++] = (char *)arg;
        } else if (arg[0] == '-' && arg[1] != '\0') {
            fprintf(stderr, "new_grep: unknown option: %s\n", arg);
            return 2;
        } else {
            if (n_op + 1 > cap_op) {
                int ncap = cap_op ? cap_op * 2 : 4;
                result = realloc(operands, (size_t)ncap * sizeof(char *));
                if (!result) { fprintf(stderr, "new_grep: out of memory\n"); return 2; }
                operands = result;
                cap_op = ncap;
            }
            operands[n_op++] = (char *)arg;
        }
    }

    if (n_op == 0) {
        fprintf(stderr, "new_grep: missing PATTERN\n");
        return 2;
    }

    const char *pattern = operands[0];
    size_t pat_len = strlen(pattern);
    char **files = operands + 1;
    int n_files = n_op - 1;

    bool any_match = false;
    bool any_error = false;

    if (n_files == 0) {
        inbuf_t ib;
        ib.fd = STDIN_FILENO;
        ib.pos = 0;
        ib.len = 0;
        memset(ib.buf, 0, sizeof(ib.buf));
        int r = search_stream(&ib, (const unsigned char *)pattern, pat_len, false, NULL);
        if (r < 0) any_error = true;
        else if (r > 0) any_match = true;
    } else {
        bool do_prefix = (n_files >= 2);
        for (int i = 0; i < n_files; i++) {
            const char *path = files[i];
            int fd = open(path, O_RDONLY);
            if (fd < 0) {
                fprintf(stderr, "new_grep: %s: %s\n", path, strerror(errno));
                any_error = true;
                continue;
            }
            struct stat st;
            if (fstat(fd, &st) < 0) {
                fprintf(stderr, "new_grep: %s: %s\n", path, strerror(errno));
                close(fd);
                any_error = true;
                continue;
            }
            if (S_ISDIR(st.st_mode)) {
                fprintf(stderr, "new_grep: %s: is a directory\n", path);
                close(fd);
                any_error = true;
                continue;
            }
            inbuf_t ib;
            ib.fd = fd;
            ib.pos = 0;
            ib.len = 0;
            memset(ib.buf, 0, sizeof(ib.buf));
            int r = search_stream(&ib, (const unsigned char *)pattern, pat_len,
                                  do_prefix, path);
            close(fd);
            if (r < 0) any_error = true;
            else if (r > 0) any_match = true;
        }
    }

    free(operands);

    if (any_error) return 2;
    if (any_match) return 0;
    return 1;
}
