#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/stat.h>
#include <sys/types.h>

/* Classify path: 1=dir (or symlink to dir), 0=non-dir, -1=missing, -2=error */
static int check_path(const char *path) {
    struct stat st;
    if (lstat(path, &st) == 0) {
        if (S_ISDIR(st.st_mode))
            return 1;
        if (S_ISLNK(st.st_mode)) {
            if (stat(path, &st) == 0)
                return S_ISDIR(st.st_mode) ? 1 : 0;
            return 0;
        }
        return 0;
    }
    if (errno == ENOENT)
        return -1;
    return -2;
}

/* mkdir -p: create missing intermediate and final directories idempotently.
   Intermediate dirs get (0777 & ~umask) | 0300; final dir gets 0777 & ~umask.
   Returns 0 on success, -1 on failure with errno set. */
static int do_mkdir_p(const char *path) {
    size_t len = strlen(path);
    if (len == 0) { errno = ENOENT; return -1; }
    if (len == 1 && path[0] == '/') return 0;

    char *buf = malloc(len + 1);
    if (!buf) { errno = ENOMEM; return -1; }

    int ok = 1;

    /* Ensure each intermediate component (at every internal '/') exists as a dir */
    for (size_t i = 0; i < len && ok; i++) {
        if (path[i] != '/' || i == 0 || i == len - 1)
            continue;
        memcpy(buf, path, i);
        buf[i] = '\0';
        int chk = check_path(buf);
        if (chk == 1)
            continue;
        if (chk == 0) { errno = ENOTDIR; ok = 0; break; }
        if (chk == -2) { ok = 0; break; }
        /* chk == -1: create it */
        if (mkdir(buf, 0777) != 0) {
            int saved = errno;
            if (check_path(buf) != 1) { errno = saved; ok = 0; }
            continue;
        }
        /* Ensure owner rwx on the newly created intermediate */
        struct stat st;
        if (lstat(buf, &st) == 0)
            chmod(buf, (mode_t)((st.st_mode & 07777) | 0300));
    }

    /* Ensure the final component */
    if (ok) {
        int chk = check_path(path);
        if (chk == 1) {
            /* already a directory: idempotent success */
        } else if (chk == 0) {
            errno = ENOTDIR;
            ok = 0;
        } else if (chk == -2) {
            ok = 0;
        } else {
            /* chk == -1: create with normal mode (kernel applies umask) */
            if (mkdir(path, 0777) != 0) {
                int saved = errno;
                if (check_path(path) != 1) { errno = saved; ok = 0; }
            }
        }
    }

    free(buf);
    return ok ? 0 : -1;
}

int main(int argc, char *argv[]) {
    int parents = 0;
    int end_of_options = 0;
    int n_operands = 0;

    /* Pass 1: validate options, count operands */
    for (int i = 1; i < argc; i++) {
        if (!end_of_options) {
            if (strcmp(argv[i], "--") == 0) {
                end_of_options = 1;
            } else if (strcmp(argv[i], "-p") == 0 ||
                       strcmp(argv[i], "--parents") == 0) {
                parents = 1;
            } else if (argv[i][0] == '-' && argv[i][1] != '\0') {
                fprintf(stderr, "mkdir: unrecognized option '%s'\n", argv[i]);
                fprintf(stderr, "Try 'mkdir --help' for more information.\n");
                return 1;
            } else {
                n_operands++;
            }
        } else {
            n_operands++;
        }
    }

    if (n_operands == 0) {
        fprintf(stderr, "mkdir: missing operand\n");
        fprintf(stderr, "Try 'mkdir --help' for more information.\n");
        return 1;
    }

    int *operands = malloc((size_t)n_operands * sizeof(int));
    if (!operands) {
        fprintf(stderr, "mkdir: memory allocation failed\n");
        return 1;
    }

    /* Pass 2: collect operand indices */
    end_of_options = 0;
    int j = 0;
    for (int i = 1; i < argc; i++) {
        if (!end_of_options) {
            if (strcmp(argv[i], "--") == 0) {
                end_of_options = 1;
            } else if (strcmp(argv[i], "-p") == 0 ||
                       strcmp(argv[i], "--parents") == 0) {
                continue;
            } else {
                operands[j++] = i;
            }
        } else {
            operands[j++] = i;
        }
    }

    /* Execute */
    int all_ok = 1;
    for (int k = 0; k < n_operands; k++) {
        const char *path = argv[operands[k]];
        int rc;
        if (parents)
            rc = do_mkdir_p(path);
        else
            rc = mkdir(path, 0777);
        if (rc != 0) {
            int err = errno;
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n",
                    path, strerror(err));
            all_ok = 0;
        }
    }

    free(operands);
    return all_ok ? 0 : 1;
}
