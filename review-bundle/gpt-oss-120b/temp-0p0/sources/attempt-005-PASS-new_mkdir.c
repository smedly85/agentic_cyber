#include <stdio.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/stat.h>
#include <unistd.h>
#include <limits.h>

static void print_error(const char *prog, const char *path) {
    // Print error in the style: prog: cannot create directory 'PATH': REASON
    fprintf(stderr, "%s: cannot create directory '%s': %s\n", prog, path, strerror(errno));
}

int main(int argc, char *argv[]) {
    const char *prog = "mkdir";
    int any_failure = 0;
    int end_of_options = 0;
    // First pass: collect operands and detect early errors.
if (argc < 2) {
        fprintf(stderr, "%s: missing operand\n", prog);
        fprintf(stderr, "Try 'mkdir --help' for more information.\n");
        return 1;
}

    // Count operands while checking for unknown options.
    int operand_count = 0;
    char **operands = malloc(sizeof(char *) * (argc - 1));
    if (!operands) {
        fprintf(stderr, "%s: memory allocation failed\n", prog);
        return 1;
    }

    for (int i = 1; i < argc; ++i) {
        char *arg = argv[i];
        if (!end_of_options && strcmp(arg, "--") == 0) {
            end_of_options = 1;
            continue;
        }
        if (!end_of_options && arg[0] == '-' && !(strcmp(arg, "-") == 0)) {
            // Unknown option
            fprintf(stderr, "%s: unrecognized option '%s'\n", prog, arg);
            fprintf(stderr, "Try 'mkdir --help' for more information.\n");
            free(operands);
            return 1;
        }
        // treat as operand
        operands[operand_count++] = arg;
    }

if (operand_count == 0) {
        fprintf(stderr, "%s: missing operand\n", prog);
        fprintf(stderr, "Try 'mkdir --help' for more information.\n");
        free(operands);
        return 1;
}

    for (int i = 0; i < operand_count; ++i) {
        char pathbuf[PATH_MAX];
        strncpy(pathbuf, operands[i], PATH_MAX - 1);
        pathbuf[PATH_MAX-1] = '\0';
        // Strip trailing slashes except when the whole path is just "/"
        size_t len = strlen(pathbuf);
        while (len > 1 && pathbuf[len-1] == '/') {
            pathbuf[--len] = '\0';
        }
        const char *path = pathbuf;
        // Determine parent directory.
        const char *slash = strrchr(path, '/');
        char parent[PATH_MAX];
        if (!slash) {
            strcpy(parent, ".");
        } else if (slash == path) {
            // Path like "/foo" – parent is root
            strncpy(parent, "/", PATH_MAX - 1);
            parent[PATH_MAX - 1] = '\0';
        } else {
            size_t len = slash - path;
            if (len >= PATH_MAX) len = PATH_MAX - 1;
            memcpy(parent, path, len);
            parent[len] = '\0';
        }

        // Check parent exists and is a directory.
        struct stat st;
        if (stat(parent, &st) != 0) {
            any_failure = 1;
            print_error(prog, path);
            continue;
        }
        if (!S_ISDIR(st.st_mode)) {
            errno = ENOTDIR; // mimic coreutils error
            any_failure = 1;
            print_error(prog, path);
            continue;
        }

        // Check if final component already exists.
        struct stat st2;
        if (stat(path, &st2) == 0) {
            errno = EEXIST;
            any_failure = 1;
            print_error(prog, path);
            continue;
        }

        // Attempt to create directory with default mode (0777 masked by umask).
        if (mkdir(path, 0777) != 0) {
            any_failure = 1;
            print_error(prog, path);
            continue;
        }
    }

    free(operands);
    return any_failure ? 1 : 0;
}
