#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>

static int ensure_dir(const char *path, mode_t um, int is_final);
static int create_parents(const char *path, mode_t um);

int main(int argc, char *argv[])
{
    int parents = 0;
    int saw_ddash = 0;
    int n_operands = 0;

    /* Pass 1: validate options, count operands. No filesystem mutation. */
    for (int i = 1; i < argc; i++) {
        const char *arg = argv[i];
        if (!saw_ddash) {
            if (strcmp(arg, "--") == 0) {
                saw_ddash = 1;
                continue;
            }
            if (arg[0] == '-' && arg[1] != '\0') {
                if (strcmp(arg, "-p") == 0 || strcmp(arg, "--parents") == 0) {
                    parents = 1;
                    continue;
                }
                if (arg[1] == '-' && arg[2] != '\0') {
                    fprintf(stderr, "mkdir: unrecognized option '%s'\n", arg);
                } else {
                    fprintf(stderr, "mkdir: invalid option -- '%c'\n", arg[1]);
                }
                fprintf(stderr, "Try 'mkdir --help' for more information.\n");
                return 1;
            }
        }
        n_operands++;
    }

    if (n_operands == 0) {
        fprintf(stderr, "mkdir: missing operand\n");
        fprintf(stderr, "Try 'mkdir --help' for more information.\n");
        return 1;
    }

    /* Capture the process umask once. */
    mode_t um = umask(0);
    umask(um);

    /* Pass 2: create each operand in order; continue after errors. */
    int exit_code = 0;
    saw_ddash = 0;
    for (int i = 1; i < argc; i++) {
        const char *arg = argv[i];
        if (!saw_ddash) {
            if (strcmp(arg, "--") == 0) {
                saw_ddash = 1;
                continue;
            }
            if (arg[0] == '-' && arg[1] != '\0') {
                continue; /* recognized option; skip */
            }
        }
        /* Operand */
        int rc;
        if (parents) {
            rc = create_parents(arg, um);
        } else {
            rc = mkdir(arg, 0777);
        }
        if (rc != 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n",
                    arg, strerror(errno));
            exit_code = 1;
        }
    }

    return exit_code;
}

/*
 * Ensure `path` exists as a directory (or is a symlink resolving to one).
 * If it does not exist, create it.
 *   is_final == 0: intermediate — chmod to (0777 & ~um) | 0300
 *   is_final == 1: final — leave as mkdir gave it (0777 & ~um)
 * Returns 0 on success, -1 on failure (errno set).
 */
static int ensure_dir(const char *path, mode_t um, int is_final)
{
    struct stat st;
    if (stat(path, &st) == 0) {
        if (S_ISDIR(st.st_mode))
            return 0;
        errno = ENOTDIR;
        return -1;
    }
    if (errno != ENOENT)
        return -1;

    if (mkdir(path, 0777) != 0) {
        if (errno == EEXIST) {
            /* Race: appeared between stat and mkdir. */
            if (stat(path, &st) == 0 && S_ISDIR(st.st_mode))
                return 0;
            errno = ENOTDIR;
        }
        return -1;
    }

    if (!is_final) {
        if (chmod(path, (0777 & ~um) | 0300) != 0)
            return -1;
    }
    return 0;
}

/*
 * Create all missing path components of `path` (for -p semantics).
 * Returns 0 on success, -1 on first failure (errno set).
 */
static int create_parents(const char *path, mode_t um)
{
    size_t len = strlen(path);
    if (len == 0) {
        errno = ENOENT;
        return -1;
    }

    char *buf = malloc(len + 1);
    if (!buf) {
        errno = ENOMEM;
        return -1;
    }
    memcpy(buf, path, len + 1);

    int result = 0;

    /* At each '/' boundary, ensure the prefix is a directory. */
    for (size_t i = 0; i < len; i++) {
        if (buf[i] != '/')
            continue;
        buf[i] = '\0';

        /* Skip empty prefix and "." prefix. */
        if (buf[0] == '\0' || strcmp(buf, ".") == 0) {
            buf[i] = '/';
            continue;
        }

        if (ensure_dir(buf, um, 0) != 0) {
            result = -1;
            goto done;
        }
        buf[i] = '/';
    }

    /* Ensure the final component. */
    if (buf[0] != '\0' && strcmp(buf, ".") != 0) {
        if (ensure_dir(buf, um, 1) != 0)
            result = -1;
    }

done:
    free(buf);
    return result;
}
