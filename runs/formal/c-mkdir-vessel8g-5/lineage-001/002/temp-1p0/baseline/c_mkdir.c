#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <stdlib.h>

#define PROGNAM "mkdir"

static int mkdir_parents(const char *path)
{
    size_t len = strlen(path);
    char *copy = malloc(len + 1);
    if (!copy)
        return -1;
    memcpy(copy, path, len + 1);

    int rc = 0;

    /* Create each intermediate prefix (delimited by '/'). */
    for (size_t i = 1; i < len; i++) {
        if (copy[i] != '/')
            continue;
        copy[i] = '\0';
        /* Skip empty string and root — they always exist as directories. */
        if (copy[0] == '\0' || strcmp(copy, "/") == 0) {
            copy[i] = '/';
            continue;
        }
        if (mkdir(copy, 0777) != 0) {
            if (errno == EEXIST) {
                struct stat st;
                if (stat(copy, &st) != 0 || !S_ISDIR(st.st_mode)) {
                    errno = ENOTDIR;
                    rc = -1;
                    break;
                }
            } else {
                rc = -1;
                break;
            }
        }
        copy[i] = '/';
    }

    /* Create (or verify) the final component. */
    if (rc == 0) {
        if (mkdir(copy, 0777) != 0) {
            if (errno == EEXIST) {
                struct stat st;
                if (stat(copy, &st) != 0 || !S_ISDIR(st.st_mode))
                    rc = -1;
                /* errno stays EEXIST — matches GNU for final-component conflict */
            } else {
                rc = -1;
            }
        }
    }

    free(copy);
    return rc;
}

int main(int argc, char *argv[])
{
    int in_positional = 0;
    int operand_count = 0;
    int any_failed = 0;
    int use_parents = 0;
    int i;

    /* Phase 1: validate — scan all arguments before any filesystem mutation. */
    for (i = 1; i < argc; i++) {
        const char *arg = argv[i];
        if (in_positional) {
            operand_count++;
        } else if (strcmp(arg, "--") == 0) {
            in_positional = 1;
        } else if (arg[0] == '-' && arg[1] != '\0') {
            if (strcmp(arg, "-p") == 0 || strcmp(arg, "--parents") == 0) {
                use_parents = 1;
            } else {
                if (arg[1] == '-') {
                    fprintf(stderr, "%s: unrecognized option '%s'\n", PROGNAM, arg);
                } else {
                    fprintf(stderr, "%s: invalid option -- '%c'\n", PROGNAM, arg[1]);
                }
                fprintf(stderr, "Try '%s --help' for more information.\n", PROGNAM);
                return 1;
            }
        } else {
            operand_count++;
        }
    }

    if (operand_count == 0) {
        fprintf(stderr, "%s: missing operand\n", PROGNAM);
        fprintf(stderr, "Try '%s --help' for more information.\n", PROGNAM);
        return 1;
    }

    /* Phase 2: create each operand in order; continue after per-operand errors. */
    in_positional = 0;
    for (i = 1; i < argc; i++) {
        const char *arg = argv[i];
        if (in_positional) {
            if (use_parents) {
                if (mkdir_parents(arg) != 0) {
                    any_failed = 1;
                    fprintf(stderr, "%s: cannot create directory '%s': %s\n",
                            PROGNAM, arg, strerror(errno));
                }
            } else {
                if (mkdir(arg, 0777) != 0) {
                    any_failed = 1;
                    fprintf(stderr, "%s: cannot create directory '%s': %s\n",
                            PROGNAM, arg, strerror(errno));
                }
            }
        } else if (strcmp(arg, "--") == 0) {
            in_positional = 1;
        } else if (arg[0] == '-' && arg[1] != '\0') {
            /* unreachable: phase 1 already rejected unknown options */
            continue;
        } else {
            if (use_parents) {
                if (mkdir_parents(arg) != 0) {
                    any_failed = 1;
                    fprintf(stderr, "%s: cannot create directory '%s': %s\n",
                            PROGNAM, arg, strerror(errno));
                }
            } else {
                if (mkdir(arg, 0777) != 0) {
                    any_failed = 1;
                    fprintf(stderr, "%s: cannot create directory '%s': %s\n",
                            PROGNAM, arg, strerror(errno));
                }
            }
        }
    }

    return any_failed;
}
