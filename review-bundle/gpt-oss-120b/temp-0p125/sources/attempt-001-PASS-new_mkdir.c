/*
 * new_mkdir - minimal mkdir implementation for checkpoint 1
 *
 * Creates one or more directories specified as operands.
 * No options are supported in this checkpoint; the parser only checks for
 * unknown options and the "--" end‑of‑options marker.
 */

#define _POSIX_C_SOURCE 200809L

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/stat.h>
#include <libgen.h>
#include <unistd.h>

static void print_error(const char *path, const char *msg) {
    fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, msg);
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        fprintf(stderr, "mkdir: missing operand\nTry 'mkdir --help' for more information.\n");
        return 1;
    }

    int have_operand = 0;
    int any_failure = 0;
    int i = 1;
    int parsing_options = 1;

    for (; i < argc; ++i) {
        char *arg = argv[i];
        if (parsing_options && strcmp(arg, "--") == 0) {
            parsing_options = 0;
            continue;
        }
        if (parsing_options && arg[0] == '-' && !(strcmp(arg, "-") == 0)) {
            /* unknown option */
            fprintf(stderr, "mkdir: unrecognized option '%s'\nTry 'mkdir --help' for more information.\n", arg);
            return 1;
        }
        have_operand = 1;

        /* Make a mutable copy of the operand and strip trailing slashes */
        char *path_copy = strdup(arg);
        if (!path_copy) {
            fprintf(stderr, "memory allocation failure\n");
            return 1;
        }
        size_t len = strlen(path_copy);
        while (len > 1 && path_copy[len-1] == '/') {
            path_copy[--len] = '\0';
        }

        /* Determine parent directory for the stripped path */
        char *parent_path = NULL;
        int parent_allocated = 0;
        const char *slash = strrchr(path_copy, '/');
        if (!slash) {
            parent_path = "."; /* current directory */
        } else if (slash == path_copy) {
            parent_path = "/"; /* root as parent */
        } else {
            size_t plen = slash - path_copy;
            parent_path = malloc(plen + 1);
            if (!parent_path) {
                fprintf(stderr, "memory allocation failure\n");
                free(path_copy);
                return 1;
            }
            memcpy(parent_path, path_copy, plen);
            ((char *)parent_path)[plen] = '\0';
            parent_allocated = 1;
        }

        struct stat sb;
        if (stat(parent_path, &sb) != 0) {
            print_error(arg, strerror(errno));
            any_failure = 1;
        } else if (!S_ISDIR(sb.st_mode)) {
            print_error(arg, "Not a directory");
            any_failure = 1;
        } else {
            /* Check that final component does not already exist */
            if (lstat(path_copy, &sb) == 0) {
                print_error(arg, "File exists");
                any_failure = 1;
            } else {
                if (mkdir(path_copy, 0777) != 0) {
                    print_error(arg, strerror(errno));
                    any_failure = 1;
                }
            }
        }

        if (parent_allocated) {
            free(parent_path);
        }
        free(path_copy);
    }

    if (!have_operand) {
        fprintf(stderr, "missing operand\n");
        return 1;
    }

    return any_failure ? 1 : 0;
}
