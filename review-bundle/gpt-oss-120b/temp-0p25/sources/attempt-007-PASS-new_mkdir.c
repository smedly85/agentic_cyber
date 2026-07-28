#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/stat.h>
#include <unistd.h>

/*
 * new_mkdir – create directories given as operands.
 * Implements the minimal behavior described in the task prompt.
 */

static void print_error(const char *path, const char *msg) {
    fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, msg);
}

int main(int argc, char *argv[]) {
    int have_double_dash = 0;
    int any_failure = 0;
    int operand_seen = 0;

    /* First pass – detect unknown options before any operand. */
    for (int i = 1; i < argc; ++i) {
        if (!have_double_dash && strcmp(argv[i], "--") == 0) {
            have_double_dash = 1;
            continue;
        }
        if (!have_double_dash && argv[i][0] == '-' && strcmp(argv[i], "-") != 0) {
            fprintf(stderr, "mkdir: unrecognized option '%s'\nTry 'mkdir --help' for more information.\n", argv[i]);
            return 1;
        }
    }

    have_double_dash = 0; /* reset for second pass */
    for (int i = 1; i < argc; ++i) {
        if (!have_double_dash && strcmp(argv[i], "--") == 0) {
            have_double_dash = 1;
            continue;
        }
        const char *orig_path = argv[i];
        /* Normalize path by removing trailing '/' characters (except when the path is just "/") */
        char *norm_path = strdup(orig_path);
        if (!norm_path) {
            perror("mkdir: memory allocation failed");
            return 1;
        }
        size_t norm_len = strlen(norm_path);
        while (norm_len > 1 && norm_path[norm_len - 1] == '/') {
            norm_path[--norm_len] = '\0';
        }
        operand_seen = 1;

        /* Determine parent directory and final component using normalized path. */
        const char *parent_path;

        char *parent_buf = NULL; /* allocated only when needed */

        const char *slash = strrchr(norm_path, '/');
        if (slash == NULL) {
            parent_path = ".";

        } else if (slash == norm_path) { /* path like "/foo" */
            parent_path = "/";

        } else {
            size_t plen = (size_t)(slash - norm_path);
            parent_buf = malloc(plen + 1);
            if (!parent_buf) {
                perror("mkdir: memory allocation failed");
                free(norm_path);
                return 1;
            }
            memcpy(parent_buf, norm_path, plen);
            parent_buf[plen] = '\0';
            parent_path = parent_buf;

        }

        /* Check that the parent exists and is a directory. */
        struct stat st_parent;
        if (stat(parent_path, &st_parent) != 0) {
            print_error(orig_path, strerror(errno));
            any_failure = 1;
            free(parent_buf);
            free(norm_path);
            continue;
        }
        if (!S_ISDIR(st_parent.st_mode)) {
            print_error(orig_path, "Not a directory");
            any_failure = 1;
            free(parent_buf);
            free(norm_path);
            continue;
        }

        /* Check whether the final component already exists. */
        struct stat st_target;
        if (stat(orig_path, &st_target) == 0) {
            print_error(orig_path, "File exists");
            any_failure = 1;
            free(parent_buf);
            free(norm_path);
            continue;
        }

        /* Attempt to create the directory. */
        if (mkdir(orig_path, 0777) != 0) {
            print_error(orig_path, strerror(errno));
            any_failure = 1;
            free(parent_buf);
            free(norm_path);
            continue;
        }

        free(parent_buf);
        free(norm_path);
    }

    if (!operand_seen) {
        fprintf(stderr, "mkdir: missing operand\nTry 'mkdir --help' for more information.\n");
        return 1;
    }

    return any_failure ? 1 : 0;
}
