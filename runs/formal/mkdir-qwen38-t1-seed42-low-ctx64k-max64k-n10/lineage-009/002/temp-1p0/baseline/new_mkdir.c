#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>

static int create_parents(const char *path)
{
    size_t len = strlen(path);
    if (len == 0) {
        errno = ENOENT;
        return -1;
    }

    char *buf = malloc(len + 1);
    if (!buf)
        return -1;

    int rc = 0;
    for (size_t i = 0; i < len; i++) {
        buf[i] = path[i];
        buf[i + 1] = '\0';

        /* Only act at '/' boundaries or at the end of the string */
        if (path[i] != '/' && i != len - 1)
            continue;

        /* Skip "/" alone — it always exists */
        if (strcmp(buf, "/") == 0)
            continue;

        if (mkdir(buf, 0777) == 0)
            continue;

        int err = errno;
        if (err == EEXIST) {
            struct stat st;
            if (stat(buf, &st) == 0 && S_ISDIR(st.st_mode))
                continue;
            /* Exists but is not a directory */
            errno = ENOTDIR;
            rc = -1;
            break;
        }
        /* ENOTDIR or any other error */
        rc = -1;
        break;
    }

    free(buf);
    return rc;
}

int main(int argc, char *argv[])
{
    int i;
    int options_done = 0;
    int parents = 0;

    /* First pass: detect unknown options (immediate failure). */
    for (i = 1; i < argc; i++) {
        if (options_done)
            continue;
        if (strcmp(argv[i], "--") == 0) {
            options_done = 1;
        } else if (strcmp(argv[i], "-p") == 0 ||
                   strcmp(argv[i], "--parents") == 0) {
            parents = 1;
        } else if (argv[i][0] == '-' && argv[i][1] != '\0') {
            fprintf(stderr, "mkdir: unrecognized option '%s'\n"
                    "Try 'mkdir --help' for more information.\n", argv[i]);
            return 1;
        }
    }

    /* Count operands. */
    options_done = 0;
    int operands = 0;
    for (i = 1; i < argc; i++) {
        if (options_done) {
            operands++;
            continue;
        }
        if (strcmp(argv[i], "--") == 0) {
            options_done = 1;
            continue;
        }
        if (strcmp(argv[i], "-p") == 0 ||
            strcmp(argv[i], "--parents") == 0)
            continue;
        operands++;
    }

    if (operands == 0) {
        fprintf(stderr, "mkdir: missing operand\n"
                "Try 'mkdir --help' for more information.\n");
        return 1;
    }

    /* Create each directory; continue after per-operand failure. */
    options_done = 0;
    int failed = 0;
    for (i = 1; i < argc; i++) {
        if (options_done) {
            /* operand after -- */
        } else if (strcmp(argv[i], "--") == 0) {
            options_done = 1;
            continue;
        } else if (strcmp(argv[i], "-p") == 0 ||
                   strcmp(argv[i], "--parents") == 0) {
            continue;
        }

        if (parents) {
            if (create_parents(argv[i]) != 0) {
                int err = errno;
                fprintf(stderr, "mkdir: cannot create directory '%s': %s\n",
                        argv[i], strerror(err));
                failed = 1;
            }
        } else {
            if (mkdir(argv[i], 0777) != 0) {
                int err = errno;
                fprintf(stderr, "mkdir: cannot create directory '%s': %s\n",
                        argv[i], strerror(err));
                failed = 1;
            }
        }
    }

    return failed ? 1 : 0;
}
