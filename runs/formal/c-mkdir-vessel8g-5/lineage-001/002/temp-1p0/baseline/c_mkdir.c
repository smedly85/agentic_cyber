#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>

static int ensure_parents(const char *path)
{
    if (path[0] == '\0') {
        errno = ENOENT;
        return 1;
    }
    size_t len = strlen(path);
    char *tmp = malloc(len + 1);
    if (!tmp) {
        errno = ENOMEM;
        return 1;
    }
    memcpy(tmp, path, len + 1);
    int is_abs = (path[0] == '/');
    int rc = 0;

    for (size_t i = 0; i <= len && !rc; i++) {
        if (i < len && path[i] != '/')
            continue;
        if (is_abs && i == 0)
            continue;

        memcpy(tmp, path, i);
        tmp[i] = '\0';
        const char *prefix = tmp;

        if (prefix[0] == '\0')
            continue;
        if (prefix[0] == '/' && prefix[1] == '\0')
            continue;

        struct stat st;
        if (lstat(prefix, &st) == 0) {
            if (S_ISDIR(st.st_mode))
                continue;
            if (S_ISLNK(st.st_mode)) {
                if (stat(prefix, &st) == 0 && S_ISDIR(st.st_mode))
                    continue;
            }
            errno = ENOTDIR;
            rc = 1;
            break;
        } else if (errno != ENOENT) {
            rc = 1;
            break;
        }

        if (mkdir(prefix, 0777) != 0) {
            int e = errno;
            if (e == EEXIST) {
                if (lstat(prefix, &st) == 0) {
                    if (S_ISDIR(st.st_mode))
                        continue;
                    if (S_ISLNK(st.st_mode) &&
                        stat(prefix, &st) == 0 && S_ISDIR(st.st_mode))
                        continue;
                }
                errno = ENOTDIR;
            }
            rc = 1;
            break;
        }

        if (lstat(prefix, &st) == 0 && S_ISDIR(st.st_mode)) {
            mode_t m = st.st_mode & 07777;
            if (!(m & (S_IWUSR | S_IXUSR))) {
                if (chmod(prefix, m | S_IWUSR | S_IXUSR) != 0) {
                    rc = 1;
                    break;
                }
            }
        }
    }

    free(tmp);
    return rc;
}

int main(int argc, char *argv[])
{
    int has_p = 0;
    int after_ddash = 0;

    /* Phase 1: Validate all arguments before any mutation. */
    for (int i = 1; i < argc; i++) {
        if (after_ddash)
            continue;
        const char *a = argv[i];
        if (strcmp(a, "--") == 0) {
            after_ddash = 1;
            continue;
        }
        if (a[0] == '-' && a[1] != '\0') {
            if (strcmp(a, "-p") == 0 || strcmp(a, "--parents") == 0) {
                has_p = 1;
                continue;
            }
            if (a[1] == '-') {
                fprintf(stderr, "mkdir: unrecognized option '%s'\n", a);
            } else {
                fprintf(stderr, "mkdir: invalid option -- '%c'\n", a[1]);
            }
            fprintf(stderr, "Try 'mkdir --help' for more information.\n");
            return 1;
        }
    }

    /* Check we have at least one operand */
    int operand_count = 0;
    after_ddash = 0;
    for (int i = 1; i < argc; i++) {
        if (after_ddash) { operand_count++; continue; }
        if (strcmp(argv[i], "--") == 0) { after_ddash = 1; continue; }
        if (argv[i][0] == '-' && argv[i][1] != '\0')
            continue;
        operand_count++;
    }
    if (operand_count == 0) {
        fprintf(stderr, "mkdir: missing operand\n");
        fprintf(stderr, "Try 'mkdir --help' for more information.\n");
        return 1;
    }

    /* Phase 2: Create each directory in order; continue after failures. */
    int exit_status = 0;
    after_ddash = 0;
    for (int i = 1; i < argc; i++) {
        int is_operand = 0;
        if (after_ddash) {
            is_operand = 1;
        } else if (strcmp(argv[i], "--") == 0) {
            after_ddash = 1;
            continue;
        } else if (argv[i][0] == '-' && argv[i][1] != '\0') {
            continue;
        } else {
            is_operand = 1;
        }

        if (!is_operand)
            continue;

        if (has_p) {
            if (ensure_parents(argv[i]) != 0) {
                fprintf(stderr, "mkdir: cannot create directory '%s': %s\n",
                        argv[i], strerror(errno));
                exit_status = 1;
            }
        } else {
            if (mkdir(argv[i], 0777) != 0) {
                int e = errno;
                fprintf(stderr, "mkdir: cannot create directory '%s': %s\n",
                        argv[i], strerror(e));
                exit_status = 1;
            }
        }
    }

    return exit_status;
}
