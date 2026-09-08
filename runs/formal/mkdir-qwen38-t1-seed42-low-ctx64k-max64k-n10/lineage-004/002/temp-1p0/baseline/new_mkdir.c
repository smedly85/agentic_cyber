#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/stat.h>
#include <sys/types.h>

static int create_parents(const char *path)
{
    size_t len = strlen(path);
    char *copy = malloc(len + 1);
    if (!copy) {
        errno = ENOMEM;
        return -1;
    }
    memcpy(copy, path, len + 1);

    size_t pos = 0;
    while (pos < len && copy[pos] == '/') pos++;

    while (pos < len) {
        size_t end = pos;
        while (end < len && copy[end] != '/') end++;

        char saved = copy[end];
        copy[end] = '\0';

        struct stat st;
        if (stat(copy, &st) == 0) {
            if (!S_ISDIR(st.st_mode)) {
                errno = ENOTDIR;
                free(copy);
                return -1;
            }
        } else {
            if (mkdir(copy, 0777) != 0) {
                if (errno == EEXIST) {
                    if (stat(copy, &st) != 0 || !S_ISDIR(st.st_mode)) {
                        errno = ENOTDIR;
                        free(copy);
                        return -1;
                    }
                } else {
                    free(copy);
                    return -1;
                }
            }
        }

        copy[end] = saved;

        if (end >= len) break;
        pos = end + 1;
        while (pos < len && copy[pos] == '/') pos++;
    }

    free(copy);
    return 0;
}

int main(int argc, char *argv[])
{
    int i;
    int end_of_options = 0;
    int num_operands = 0;
    int parents = 0;

    /* First pass: reject unknown options, count operands, detect -p */
    for (i = 1; i < argc; i++) {
        if (!end_of_options) {
            if (strcmp(argv[i], "--") == 0) {
                end_of_options = 1;
                continue;
            }
            if (strcmp(argv[i], "-p") == 0 || strcmp(argv[i], "--parents") == 0) {
                parents = 1;
                continue;
            }
            if (argv[i][0] == '-' && strcmp(argv[i], "-") != 0) {
                fprintf(stderr, "mkdir: unrecognized option '%s'\nTry 'mkdir --help' for more information.\n", argv[i]);
                return 1;
            }
        }
        num_operands++;
    }

    if (num_operands == 0) {
        fprintf(stderr, "mkdir: missing operand\nTry 'mkdir --help' for more information.\n");
        return 1;
    }

    /* Second pass: attempt to create each directory */
    int any_failed = 0;
    end_of_options = 0;

    for (i = 1; i < argc; i++) {
        if (!end_of_options) {
            if (strcmp(argv[i], "--") == 0) {
                end_of_options = 1;
                continue;
            }
            if (strcmp(argv[i], "-p") == 0 || strcmp(argv[i], "--parents") == 0) {
                continue;
            }
        }
        const char *path = argv[i];
        int rc;
        if (parents) {
            rc = create_parents(path);
        } else {
            rc = (mkdir(path, 0777) != 0);
        }
        if (rc != 0) {
            any_failed = 1;
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n",
                    path, strerror(errno));
        }
    }

    return any_failed ? 1 : 0;
}
