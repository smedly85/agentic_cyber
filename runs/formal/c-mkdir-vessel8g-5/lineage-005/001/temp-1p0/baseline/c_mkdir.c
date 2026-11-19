#define _POSIX_C_SOURCE 200809L

#include <errno.h>
#include <stdio.h>
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

int main(int argc, char **argv) {
    int seen_dd = 0;
    int n_op = 0;

    for (int i = 1; i < argc; i++) {
        const char *a = argv[i];
        if (seen_dd) {
            n_op++;
        } else if (strcmp(a, "--") == 0) {
            seen_dd = 1;
        } else if (a[0] == '-' && strcmp(a, "-") != 0) {
            diag_unknown_option(a, strlen(a));
            return 1;
        } else {
            n_op++;
        }
    }

    if (n_op == 0) {
        diag_missing_operand();
        return 1;
    }

    seen_dd = 0;
    int rc = 0;

    for (int i = 1; i < argc; i++) {
        const char *a = argv[i];
        if (seen_dd) {
            if (mkdir(a, 0777) != 0) {
                rc = 1;
                diag_create_fail(a, strlen(a), errno);
            }
        } else if (strcmp(a, "--") == 0) {
            seen_dd = 1;
        } else if (a[0] == '-' && strcmp(a, "-") != 0) {
            continue;
        } else {
            if (mkdir(a, 0777) != 0) {
                rc = 1;
                diag_create_fail(a, strlen(a), errno);
            }
        }
    }

    return rc;
}
