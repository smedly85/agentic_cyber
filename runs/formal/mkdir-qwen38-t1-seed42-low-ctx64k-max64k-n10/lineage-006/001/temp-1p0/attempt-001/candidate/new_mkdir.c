#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>

static int make_parents(const char *path)
{
    size_t len = strlen(path);
    char *copy = malloc(len + 1);
    if (!copy)
        return -1;
    memcpy(copy, path, len + 1);

    int failed = 0;

    /* Create each missing intermediate component in order. */
    for (size_t i = 1; i < len; i++) {
        if (copy[i] == '/') {
            copy[i] = '\0';
            if (copy[0] != '\0') {
                int rc = mkdir(copy, 0777);
                if (rc != 0 && errno != EEXIST) {
                    failed = 1;
                    break;
                }
                if (rc != 0) {
                    /* EEXIST: must be a directory to continue through it. */
                    struct stat st;
                    if (stat(copy, &st) != 0 || !S_ISDIR(st.st_mode)) {
                        errno = ENOTDIR;
                        failed = 1;
                        break;
                    }
                }
            }
            copy[i] = '/';
        }
    }

    /* Create the final component, or accept it if it is already a directory. */
    if (!failed) {
        if (mkdir(copy, 0777) != 0) {
            if (errno == EEXIST) {
                struct stat st;
                if (stat(copy, &st) != 0 || !S_ISDIR(st.st_mode)) {
                    /* exists but is not a directory: failure (EEXIST) */
                    failed = 1;
                }
                /* exists and is a directory: success, do not change mode */
            } else {
                failed = 1;
            }
        }
    }

    free(copy);
    return failed;
}

int main(int argc, char *argv[])
{
    int have_operands = 0;
    int any_failure = 0;
    int end_of_options = 0;
    int parents = 0;

    for (int i = 1; i < argc; i++) {
        if (!end_of_options && strcmp(argv[i], "--") == 0) {
            end_of_options = 1;
            continue;
        }
        if (!end_of_options && argv[i][0] == '-' && argv[i][1] != '\0') {
            if (strcmp(argv[i], "-p") == 0 || strcmp(argv[i], "--parents") == 0) {
                parents = 1;
                continue;
            }
            fprintf(stderr, "mkdir: unrecognized option '%s'\n", argv[i]);
            fprintf(stderr, "Try 'mkdir --help' for more information.\n");
            return 1;
        }
        have_operands = 1;
        int rc;
        if (parents) {
            rc = make_parents(argv[i]);
        } else {
            rc = (mkdir(argv[i], 0777) != 0) ? -1 : 0;
        }
        if (rc != 0) {
            any_failure = 1;
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n",
                    argv[i], strerror(errno));
        }
    }

    if (!have_operands) {
        fprintf(stderr, "mkdir: missing operand\n");
        fprintf(stderr, "Try 'mkdir --help' for more information.\n");
        return 1;
    }

    return any_failure ? 1 : 0;
}
