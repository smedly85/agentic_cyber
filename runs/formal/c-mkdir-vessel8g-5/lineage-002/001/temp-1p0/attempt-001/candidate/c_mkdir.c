#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>

#define MAX_PATH_LEN 4096

static int create_parents(const char *path, mode_t um)
{
    char buf[MAX_PATH_LEN];
    size_t buflen = 0;
    size_t i = 0;
    size_t len = strlen(path);

    if (len == 0)
        return -1;

    if (path[0] == '/')
        buf[buflen++] = '/';

    int found = 0;

    while (i < len) {
        while (i < len && path[i] == '/')
            i++;
        if (i >= len)
            break;

        size_t start = i;
        while (i < len && path[i] != '/')
            i++;
        size_t clen = i - start;
        if (clen == 0)
            continue;

        /* Determine if this is the last non-empty component. */
        int is_last = 1;
        for (size_t j = i; j < len; j++) {
            if (path[j] != '/') {
                is_last = 0;
                break;
            }
        }

        if (buflen > 0 && buf[buflen - 1] != '/')
            buf[buflen++] = '/';
        if (buflen + clen >= sizeof(buf)) {
            errno = ENAMETOOLONG;
            return -1;
        }
        memcpy(buf + buflen, path + start, clen);
        buflen += clen;
        buf[buflen] = '\0';

        found = 1;

        struct stat st;
        if (lstat(buf, &st) == 0) {
            if (S_ISDIR(st.st_mode))
                continue;
            if (S_ISLNK(st.st_mode)) {
                if (stat(buf, &st) == 0 && S_ISDIR(st.st_mode))
                    continue;
                errno = ENOTDIR;
                return -1;
            }
            errno = ENOTDIR;
            return -1;
        }

        if (errno != ENOENT)
            return -1;

        mode_t mode = is_last ? (0777 & ~um) : ((0777 & ~um) | 0300);
        if (mkdir(buf, mode) != 0)
            return -1;
    }

    if (!found) {
        struct stat st;
        if (lstat(path, &st) == 0) {
            if (S_ISDIR(st.st_mode))
                return 0;
            if (S_ISLNK(st.st_mode)) {
                if (stat(path, &st) == 0 && S_ISDIR(st.st_mode))
                    return 0;
            }
            errno = ENOTDIR;
        }
        return -1;
    }

    return 0;
}

int main(int argc, char *argv[])
{
    int parents = 0;
    int n_operands = 0;
    int unknown_idx = -1;

    /* Pass 1: validate all arguments before any filesystem mutation. */
    int after_ddash = 0;
    for (int i = 1; i < argc; i++) {
        if (after_ddash) {
            n_operands++;
        } else if (argv[i][0] == '-' && argv[i][1] == '-' && argv[i][2] == '\0') {
            after_ddash = 1;
        } else if (argv[i][0] == '-' && argv[i][1] != '\0') {
            if (strcmp(argv[i], "-p") == 0 || strcmp(argv[i], "--parents") == 0) {
                parents = 1;
            } else if (unknown_idx < 0) {
                unknown_idx = i;
            }
        } else {
            n_operands++;
        }
    }

    if (unknown_idx >= 0) {
        const char *a = argv[unknown_idx];
        if (a[1] == '-' && a[2] != '\0')
            fprintf(stderr, "mkdir: unrecognized option '%s'\n", a);
        else
            fprintf(stderr, "mkdir: invalid option -- '%c'\n", a[1]);
        fprintf(stderr, "Try 'mkdir --help' for more information.\n");
        return 1;
    }

    if (n_operands == 0) {
        fprintf(stderr, "mkdir: missing operand\n");
        fprintf(stderr, "Try 'mkdir --help' for more information.\n");
        return 1;
    }

    /* Determine umask for -p intermediate mode computation. */
    mode_t um = 0;
    if (parents) {
        um = umask(0);
        umask(um);
    }

    /* Pass 2: create directories; continue after per-operand errors. */
    after_ddash = 0;
    int rc = 0;
    for (int i = 1; i < argc; i++) {
        const char *path;

        if (after_ddash) {
            path = argv[i];
        } else if (argv[i][0] == '-' && argv[i][1] == '-' && argv[i][2] == '\0') {
            after_ddash = 1;
            continue;
        } else if (argv[i][0] == '-' && argv[i][1] != '\0') {
            continue; /* known option, skip */
        } else {
            path = argv[i];
        }

        int err;
        if (parents) {
            err = (create_parents(path, um) != 0);
        } else {
            err = (mkdir(path, 0777) != 0);
        }
        if (err) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n",
                    path, strerror(errno));
            rc = 1;
        }
    }

    return rc;
}
