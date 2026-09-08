#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/stat.h>
#include <sys/types.h>

int main(int argc, char *argv[]) {
    const char *prog = (argc > 0) ? argv[0] : "new_mkdir";

    /* First pass: validate arguments before creating anything */
    int operand_count = 0;
    int end_of_options = 0;

    for (int i = 1; i < argc; i++) {
        if (!end_of_options) {
            if (strcmp(argv[i], "--") == 0) {
                end_of_options = 1;
                continue;
            }
            if (argv[i][0] == '-' && argv[i][1] != '\0') {
                fprintf(stderr, "%s: unrecognized option '%s'\n", prog, argv[i]);
                fprintf(stderr, "Try '%s --help' for more information.\n", prog);
                return 1;
            }
        }
        operand_count++;
    }

    if (operand_count == 0) {
        fprintf(stderr, "%s: missing operand\n", prog);
        fprintf(stderr, "Try '%s --help' for more information.\n", prog);
        return 1;
    }

    /* Second pass: attempt to create each directory */
    int any_failed = 0;
    end_of_options = 0;

    for (int i = 1; i < argc; i++) {
        if (!end_of_options) {
            if (strcmp(argv[i], "--") == 0) {
                end_of_options = 1;
                continue;
            }
        }

        const char *path = argv[i];

        /* Strip trailing slashes (but keep at least one for absolute paths) */
        size_t len = strlen(path);
        while (len > 1 && path[len - 1] == '/') {
            len--;
        }
        /* If result is empty (path was all slashes), it's "/" */
        if (len == 0) {
            len = 1;
        }

        char *path_buf = NULL;
        if (len < strlen(path)) {
            path_buf = malloc(len + 1);
            if (!path_buf) {
                fprintf(stderr, "%s: memory allocation failed\n", prog);
                return 1;
            }
            memcpy(path_buf, path, len);
            path_buf[len] = '\0';
            path = path_buf;
        }

        char *last_slash = strrchr(path, '/');
        const char *parent = ".";
        char *parent_alloc = NULL;

        if (last_slash != NULL) {
            if (last_slash == path) {
                /* Path is "/" — parent is "/", component is "" (root exists) */
                parent = "/";
            } else {
                size_t plen = (size_t)(last_slash - path);
                parent_alloc = malloc(plen + 1);
                if (!parent_alloc) {
                    fprintf(stderr, "%s: memory allocation failed\n", prog);
                    free(path_buf);
                    return 1;
                }
                memcpy(parent_alloc, path, plen);
                parent_alloc[plen] = '\0';
                parent = parent_alloc;
            }
        }

        struct stat st;

        /* Check parent exists */
        if (stat(parent, &st) != 0) {
            fprintf(stderr, "%s: cannot create directory '%s': %s\n",
                    argv[i], strerror(errno));
            any_failed = 1;
            free(parent_alloc);
            free(path_buf);
            continue;
        }

        /* Check parent is a directory */
        if (!S_ISDIR(st.st_mode)) {
            fprintf(stderr,
                    "%s: cannot create directory '%s': Not a directory\n",
                    argv[i]);
            any_failed = 1;
            free(parent_alloc);
            free(path_buf);
            continue;
        }

        /* Check the target does not already exist */
        if (lstat(path, &st) == 0) {
            fprintf(stderr,
                    "%s: cannot create directory '%s': File exists\n",
                    argv[i]);
            any_failed = 1;
            free(parent_alloc);
            free(path_buf);
            continue;
        }

        /* Create the directory */
        if (mkdir(path, 0777) != 0) {
            fprintf(stderr, "%s: cannot create directory '%s': %s\n",
                    argv[i], strerror(errno));
            any_failed = 1;
            free(parent_alloc);
            free(path_buf);
            continue;
        }

        free(parent_alloc);
        free(path_buf);
    }

    return any_failed ? 1 : 0;
}
