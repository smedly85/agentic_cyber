#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <errno.h>

/*
 * new_mkdir – minimal mkdir implementation for the checkpoint.
 * Behaves according to the specification in the task description.
 */

static void print_error(const char *path, const char *msg) {
    fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, msg);
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        // No arguments at all.
        fprintf(stderr, "new_mkdir: missing operand\n");
        return 1;
    }

    int end_of_options = 0;
    int operands_count = 0;
    const char **operands = malloc((argc - 1) * sizeof(char *));
    if (!operands) {
        fprintf(stderr, "new_mkdir: memory allocation failed\n");
        return 1;
    }

    // Parse arguments.
    for (int i = 1; i < argc; ++i) {
        const char *arg = argv[i];
        if (!end_of_options && strcmp(arg, "--") == 0) {
            end_of_options = 1;
            continue;
        }
        if (!end_of_options && arg[0] == '-' && !(strcmp(arg, "-") == 0)) {
            // Unknown option.
            fprintf(stderr, "new_mkdir: unrecognized option '%s'\n", arg);
            free((void *)operands);
            return 1;
        }
        // Operand.
        operands[operands_count++] = arg;
    }

    if (operands_count == 0) {
        fprintf(stderr, "new_mkdir: missing operand\n");
        free((void *)operands);
        return 1;
    }

    int any_failed = 0;
    for (int i = 0; i < operands_count; ++i) {
        const char *path = operands[i];
        // Determine parent directory.
        const char *slash = strrchr(path, '/');
        char *parent = NULL;
        if (!slash) {
            parent = strdup(".");
        } else if (slash == path) { // Path like "/foo"
            size_t len = 1; // just root slash
            parent = malloc(len + 1);
            if (parent) {
                memcpy(parent, "/", 1);
                parent[1] = '\0';
            }
        } else {
            size_t len = slash - path;
            parent = malloc(len + 1);
            if (parent) {
                memcpy(parent, path, len);
                parent[len] = '\0';
            }
        }
        if (!parent) {
            fprintf(stderr, "new_mkdir: memory allocation failed\n");
            any_failed = 1;
            continue;
        }

        struct stat st;
        if (stat(parent, &st) != 0) {
            print_error(path, strerror(errno));
            any_failed = 1;
            free(parent);
            continue;
        }
        if (!S_ISDIR(st.st_mode)) {
            print_error(path, "Not a directory");
            any_failed = 1;
            free(parent);
            continue;
        }
        free(parent);

        // Check if final component already exists.
        struct stat st2;
        if (stat(path, &st2) == 0) {
            print_error(path, "File exists");
            any_failed = 1;
            continue;
        }
        // Attempt to create directory with default mode (umask applied).
        if (mkdir(path, 0777) != 0) {
            print_error(path, strerror(errno));
            any_failed = 1;
            continue;
        }
    }

    free((void *)operands);
    return any_failed ? 1 : 0;
}
