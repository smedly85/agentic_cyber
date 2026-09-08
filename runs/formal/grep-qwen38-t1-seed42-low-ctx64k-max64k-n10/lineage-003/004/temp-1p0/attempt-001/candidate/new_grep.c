#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdbool.h>
#include <errno.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <dirent.h>

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

static unsigned char fold_byte(unsigned char c) {
    if (c >= 0x41 && c <= 0x5A) return c + 0x20;
    return c;
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

static int line_matches(const unsigned char *line, size_t line_len,
                        const unsigned char *pat, size_t pat_len,
                        bool ignore_case) {
    if (!ignore_case) {
        return pattern_match(line, line_len, pat, pat_len);
    }
    unsigned char *folded = malloc(line_len ? line_len : 1);
    if (!folded) return 0;
    for (size_t i = 0; i < line_len; i++) folded[i] = fold_byte(line[i]);
    int r = pattern_match(folded, line_len, pat, pat_len);
    free(folded);
    return r;
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
                         bool prefix, const char *name, bool ignore_case) {
    int found = 0;
    linebuf_t lb = {0};
    int rc = 0;

    for (;;) {
        unsigned char c;
        int r = inbuf_get(ib, &c);
        if (r < 0) { rc = -1; break; }
        if (r == 0) {
            if (lb.len > 0) {
                if (line_matches(lb.data, lb.len, pat, pat_len, ignore_case)) {
                    if (emit_line(lb.data, lb.len, prefix, name) < 0) { rc = -1; break; }
                    found = 1;
                }
            }
            break;
        }
        if (c == '\n') {
            if (line_matches(lb.data, lb.len, pat, pat_len, ignore_case)) {
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

static int search_file(const char *path, const unsigned char *pat, size_t pat_len,
                       bool prefix, bool ignore_case, bool *any_match, bool *any_error) {
    int fd = open(path, O_RDONLY);
    if (fd < 0) {
        fprintf(stderr, "new_grep: %s: %s\n", path, strerror(errno));
        *any_error = true;
        return -1;
    }
    struct stat st;
    if (fstat(fd, &st) < 0) {
        fprintf(stderr, "new_grep: %s: %s\n", path, strerror(errno));
        close(fd);
        *any_error = true;
        return -1;
    }
    if (S_ISDIR(st.st_mode)) {
        close(fd);
        return 0;
    }
    inbuf_t ib;
    ib.fd = fd;
    ib.pos = 0;
    ib.len = 0;
    memset(ib.buf, 0, sizeof(ib.buf));
    int r = search_stream(&ib, pat, pat_len, prefix, path, ignore_case);
    close(fd);
    if (r < 0) {
        *any_error = true;
        return -1;
    }
    if (r > 0) {
        *any_match = true;
    }
    return 0;
}

static int name_cmp(const void *a, const void *b) {
    const unsigned char *sa = *(const unsigned char *const *)a;
    const unsigned char *sb = *(const unsigned char *const *)b;
    while (*sa && *sb && *sa == *sb) { sa++; sb++; }
    return (int)*sa - (int)*sb;
}

static int search_dir(const char *dirpath, const unsigned char *pat, size_t pat_len,
                      bool prefix, bool ignore_case, bool *any_match, bool *any_error) {
    DIR *dir = opendir(dirpath);
    if (!dir) {
        fprintf(stderr, "new_grep: %s: %s\n", dirpath, strerror(errno));
        *any_error = true;
        return -1;
    }

    char **names = NULL;
    int n = 0, cap = 0;
    struct dirent *entry;
    while ((entry = readdir(dir)) != NULL) {
        if (strcmp(entry->d_name, ".") == 0 || strcmp(entry->d_name, "..") == 0)
            continue;
        if (n + 1 > cap) {
            int ncap = cap ? cap * 2 : 64;
            char **nn = realloc(names, (size_t)ncap * sizeof(char *));
            if (!nn) {
                for (int i = 0; i < n; i++) free(names[i]);
                free(names);
                closedir(dir);
                *any_error = true;
                return -1;
            }
            names = nn;
            cap = ncap;
        }
        size_t len = strlen(entry->d_name) + 1;
        names[n] = malloc(len);
        if (!names[n]) {
            for (int i = 0; i < n; i++) free(names[i]);
            free(names);
            closedir(dir);
            *any_error = true;
            return -1;
        }
        memcpy(names[n], entry->d_name, len);
        n++;
    }
    closedir(dir);

    qsort(names, (size_t)n, sizeof(char *), name_cmp);

    size_t dl = strlen(dirpath);
    bool need_sep = !(dl > 0 && dirpath[dl - 1] == '/');

    for (int i = 0; i < n; i++) {
        size_t path_len = dl + (need_sep ? 1 : 0) + strlen(names[i]) + 1;
        char *path = malloc(path_len);
        if (!path) {
            for (int j = 0; j < n; j++) free(names[j]);
            free(names);
            *any_error = true;
            return -1;
        }
        if (need_sep)
            snprintf(path, path_len, "%s/%s", dirpath, names[i]);
        else
            snprintf(path, path_len, "%s%s", dirpath, names[i]);

        struct stat st;
        if (lstat(path, &st) < 0) {
            fprintf(stderr, "new_grep: %s: %s\n", path, strerror(errno));
            free(path);
            continue;
        }

        if (S_ISDIR(st.st_mode)) {
            search_dir(path, pat, pat_len, prefix, ignore_case, any_match, any_error);
        } else if (S_ISREG(st.st_mode)) {
            search_file(path, pat, pat_len, prefix, ignore_case, any_match, any_error);
        }

        free(path);
    }

    for (int i = 0; i < n; i++) free(names[i]);
    free(names);
    return 0;
}

int main(int argc, char *argv[]) {
    char **operands = NULL;
    int n_op = 0, cap_op = 0;
    int seen_ddash = 0;
    enum prefix_mode { PREFIX_DEFAULT, PREFIX_ON, PREFIX_OFF };
    enum prefix_mode pmode = PREFIX_DEFAULT;
    bool recursive = false;
    bool ignore_case = false;

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
        } else if (arg[0] == '-' && arg[1] == '-' && arg[2] != '\0') {
            if (strcmp(arg, "--with-filename") == 0)
                pmode = PREFIX_ON;
            else if (strcmp(arg, "--no-filename") == 0)
                pmode = PREFIX_OFF;
            else if (strcmp(arg, "--recursive") == 0)
                recursive = true;
            else if (strcmp(arg, "--ignore-case") == 0)
                ignore_case = true;
            else {
                fprintf(stderr, "new_grep: unknown option: %s\n", arg);
                return 2;
            }
        } else if (arg[0] == '-' && arg[1] != '\0') {
            for (const char *p = arg + 1; *p; p++) {
                if (*p == 'H')
                    pmode = PREFIX_ON;
                else if (*p == 'h')
                    pmode = PREFIX_OFF;
                else if (*p == 'r')
                    recursive = true;
                else if (*p == 'i')
                    ignore_case = true;
                else {
                    fprintf(stderr, "new_grep: unknown option: %s\n", arg);
                    return 2;
                }
            }
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

    unsigned char *folded_pat = NULL;
    const unsigned char *match_pat = (const unsigned char *)pattern;
    if (ignore_case) {
        folded_pat = (unsigned char *)malloc(pat_len ? pat_len : 1);
        for (size_t i = 0; i < pat_len; i++)
            folded_pat[i] = fold_byte((unsigned char)pattern[i]);
        match_pat = folded_pat;
    }

    bool any_match = false;
    bool any_error = false;

    if (n_files == 0) {
        inbuf_t ib;
        ib.fd = STDIN_FILENO;
        ib.pos = 0;
        ib.len = 0;
        memset(ib.buf, 0, sizeof(ib.buf));
        bool stdin_prefix = (pmode == PREFIX_ON);
        int r = search_stream(&ib, match_pat, pat_len,
                              stdin_prefix, stdin_prefix ? "(standard input)" : NULL,
                              ignore_case);
        if (r < 0) any_error = true;
        else if (r > 0) any_match = true;
    } else {
        bool do_prefix;
        if (pmode == PREFIX_ON) do_prefix = true;
        else if (pmode == PREFIX_OFF) do_prefix = false;
        else if (n_files >= 2) do_prefix = true;
        else if (recursive) {
            do_prefix = false;
            for (int i = 0; i < n_files; i++) {
                struct stat st2;
                if (lstat(files[i], &st2) == 0 && S_ISDIR(st2.st_mode)) {
                    do_prefix = true;
                    break;
                }
            }
        } else do_prefix = false;

        if (recursive) {
            for (int i = 0; i < n_files; i++) {
                const char *path = files[i];
                struct stat st;
                if (lstat(path, &st) < 0) {
                    fprintf(stderr, "new_grep: %s: %s\n", path, strerror(errno));
                    any_error = true;
                    continue;
                }
                if (S_ISDIR(st.st_mode)) {
                    search_dir(path, match_pat, pat_len,
                               do_prefix, ignore_case, &any_match, &any_error);
                } else {
                    search_file(path, match_pat, pat_len,
                                do_prefix, ignore_case, &any_match, &any_error);
                }
            }
        } else {
            for (int i = 0; i < n_files; i++) {
                const char *path = files[i];
                struct stat st;
                if (lstat(path, &st) < 0) {
                    fprintf(stderr, "new_grep: %s: %s\n", path, strerror(errno));
                    any_error = true;
                    continue;
                }
                if (S_ISDIR(st.st_mode)) {
                    fprintf(stderr, "new_grep: %s: is a directory\n", path);
                    any_error = true;
                    continue;
                }
                search_file(path, match_pat, pat_len,
                            do_prefix, ignore_case, &any_match, &any_error);
            }
        }
    }

    free(folded_pat);
    free(operands);

    if (any_error) return 2;
    if (any_match) return 0;
    return 1;
}
