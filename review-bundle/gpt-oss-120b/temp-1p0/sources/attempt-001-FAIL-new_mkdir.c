#include <stdio.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/stat.h>
#include <unistd.h>

static void print_error(const char *path, const char *msg) {
    fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, msg);
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        fprintf(stderr, "mkdir: missing operand\nTry 'mkdir --help' for more information.\n");
        return 1;
    }

    int any_failure = 0;
    int end_of_options = 0;
    int operands_start = argc; // index of first operand after validation
    for (int i = 1; i < argc; ++i) {
        const char *arg = argv[i];
        if (!end_of_options && strcmp(arg, "--") == 0) {
            end_of_options = 1;
            continue;
        }
        if (!end_of_options && arg[0] == '-' && !(strcmp(arg, "-") == 0)) {
            fprintf(stderr, "mkdir: unrecognized option '%s'\nTry 'mkdir --help' for more information.\n", arg);
            return 1;
        }
        // treat as operand
        operands_start = i;
        break; // first operand found, stop scanning for options
    }

    if (operands_start == argc) {
        // No operands after option processing
        fprintf(stderr, "mkdir: missing operand\nTry 'mkdir --help' for more information.\n");
        return 1;
    }

    for (int i = operands_start; i < argc; ++i) {
        const char *path = argv[i];
        if (!end_of_options && strcmp(path, "--") == 0) {
            // '--' after first operand is treated as operand per spec? Actually stop processing options earlier.
            continue;
        }
        /* Normalize path: strip trailing '/' characters (unless the whole path is "/"). */
        char *norm = strdup(path);
        if (!norm) {
            print_error(path, "Out of memory");
            any_failure = 1;
            continue;
        }
        size_t nlen = strlen(norm);
        while (nlen > 1 && norm[nlen-1] == '/') {
            norm[--nlen] = '\0';
        }
        // Determine parent directory using normalized path
        char *slash = strrchr(norm, '/');
        const char *parent;
        if (slash == NULL) {
            parent = "."; // current directory
        } else {
            if (slash == norm) { // path like "/foo"
                *(slash + 1) = '\0'; // keep leading slash as root
            } else {
                *slash = '\0';
            }
            parent = norm;
        }
        struct stat st;
        if (stat(parent, &st) != 0) {
            print_error(path, strerror(errno));
            any_failure = 1;
            free(norm);
            continue;
        }
        if (!S_ISDIR(st.st_mode)) {
            print_error(path, "Not a directory");
            any_failure = 1;
            free(norm);
            continue;
        }
        // Check if final component already exists (use normalized path)
        struct stat st2;
        if (lstat(norm, &st2) == 0) {
            print_error(path, "File exists");
            any_failure = 1;
            free(norm);
            continue;
        }
        // Attempt to create directory with default mode (0777 masked by umask)
        if (mkdir(norm, 0777) != 0) {
            print_error(path, strerror(errno));
            any_failure = 1;
            free(norm);
            continue;
        }
        free(norm);
    }

    return any_failure ? 1 : 0;
}
