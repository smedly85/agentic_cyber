#define _POSIX_C_SOURCE 200809L

#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

static void write_quoted(const char *s, size_t len) {
    fputc('\'', stderr);
    for (size_t i = 0; i < len; i++) {
        unsigned char c = (unsigned char)s[i];
        if (c == '\'') {
            fputs("'\''", stderr);
        } else if (c >= 0x20 && c <= 0x7e) {
            fputc(c, stderr);
        } else {
            fprintf(stderr, "\\%03o", c);
        }
    }
    fputc('\'', stderr);
}

static void diag_create_fail(const char *name, size_t len, int err) {
    fprintf(stderr, "mkdir: cannot create directory ");
    write_quoted(name, len);
    fprintf(stderr, ": %s\n", strerror(err));
}

static void diag_unknown_option(const char *opt, size_t len) {
    fprintf(stderr, "mkdir: unrecognized option ");
    write_quoted(opt, len);
    fprintf(stderr, "\nTry 'mkdir --help' for more information.\n");
}

static void diag_missing_operand(void) {
    fprintf(stderr, "mkdir: missing operand\n");
    fprintf(stderr, "Try 'mkdir --help' for more information.\n");
}

static int create_parents(const char *path) {
    size_t len = strlen(path);
    if (len == 0) { errno = ENOENT; return -1; }

    char *buf = malloc(len + 1);
    if (!buf) { errno = ENOMEM; return -1; }

    /* Determine the end position of the last valid (non-empty, non-dot)
       component so we can tell intermediate dirs from the final one. */
    size_t last_comp_end = 0;
    {
        size_t scan = (path[0] == '/') ? 1 : 0;
        while (scan < len) {
            while (scan < len && path[scan] == '/') scan++;
            if (scan >= len) break;
            size_t cs = scan;
            while (scan < len && path[scan] != '/') scan++;
            size_t cl = scan - cs;
            if (cl > 0 && !(cl == 1 && path[cs] == '.'))
                last_comp_end = scan;
        }
    }

    int rc = 0;
    size_t pos = (path[0] == '/') ? 1 : 0;

    while (pos < len) {
        while (pos < len && path[pos] == '/') pos++;
        if (pos >= len) break;

        size_t comp_start = pos;
        while (pos < len && path[pos] != '/') pos++;
        size_t comp_len = pos - comp_start;

        if (comp_len == 0) continue;
        if (comp_len == 1 && path[comp_start] == '.') continue;

        memcpy(buf, path, pos);
        buf[pos] = '\0';

        struct stat st;
        if (stat(buf, &st) == 0) {
            if (S_ISDIR(st.st_mode)) continue;
            errno = ENOTDIR; rc = -1; goto done;
        } else if (errno == ENOENT) {
            /* Could be a broken symlink: lstat will reveal it. */
            struct stat st_l;
            if (lstat(buf, &st_l) == 0) {
                errno = ENOTDIR; rc = -1; goto done;
            }
            /* Truly absent: fall through to create. */
        } else {
            rc = -1; goto done;
        }

        if (mkdir(buf, 0777) != 0) { rc = -1; goto done; }

        /* Intermediate components: ensure owner has write+search (0300). */
        if (pos != last_comp_end) {
            struct stat st2;
            if (stat(buf, &st2) == 0) {
                mode_t m = st2.st_mode & 07777;
                if ((m & 0300) != 0300)
                    chmod(buf, m | 0300);
            }
        }
    }

done:
    free(buf);
    return rc;
}

int main(int argc, char **argv) {
    int parents = 0;
    int seen_dd = 0;
    int n_op = 0;

    /* Pass 1: validate options, count operands. */
    for (int i = 1; i < argc; i++) {
        const char *a = argv[i];
        if (seen_dd) {
            n_op++;
        } else if (strcmp(a, "--") == 0) {
            seen_dd = 1;
        } else if (a[0] == '-' && strcmp(a, "-") != 0) {
            if (strcmp(a, "-p") == 0 || strcmp(a, "--parents") == 0)
                parents = 1;
            else {
                diag_unknown_option(a, strlen(a));
                return 1;
            }
        } else {
            n_op++;
        }
    }

    if (n_op == 0) {
        diag_missing_operand();
        return 1;
    }

    /* Pass 2: create directories, continue after per-operand errors. */
    seen_dd = 0;
    int rc = 0;

    for (int i = 1; i < argc; i++) {
        const char *a = argv[i];
        int is_op;
        if (seen_dd) {
            is_op = 1;
        } else if (strcmp(a, "--") == 0) {
            seen_dd = 1;
            is_op = 0;
        } else if (a[0] == '-' && strcmp(a, "-") != 0) {
            is_op = 0;
        } else {
            is_op = 1;
        }

        if (!is_op) continue;

        int r = parents ? create_parents(a) : (mkdir(a, 0777) == 0 ? 0 : -1);
        if (r != 0) {
            rc = 1;
            diag_create_fail(a, strlen(a), errno);
        }
    }

    return rc;
}
