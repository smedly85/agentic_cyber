#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/stat.h>
#include <unistd.h>
#include <limits.h>

static void print_error(const char *path, const char *msg) {
    fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, msg);
}

int main(int argc, char *argv[]) {
    int any_failure = 0;
    int seen_double_dash = 0;
    int operand_count = 0;

    // First pass to validate options and collect operands positions.
    for (int i = 1; i < argc; ++i) {
        const char *arg = argv[i];
        if (!seen_double_dash && strcmp(arg, "--") == 0) {
            seen_double_dash = 1;
            continue;
        }
        if (!seen_double_dash && arg[0] == '-' && !(strcmp(arg, "-") == 0)) {
            // Unknown option
            fprintf(stderr, "mkdir: unrecognized option '%s'\n", arg);
            return 1;
        }
        // Operand
        operand_count++;
    }

    if (operand_count == 0) {
        fprintf(stderr, "mkdir: missing operand\n");
        return 1;
    }

    // Second pass: actually process operands in order.
    for (int i = 1; i < argc; ++i) {
        const char *arg = argv[i];
        if (!seen_double_dash && strcmp(arg, "--") == 0) {
            seen_double_dash = 1;
            continue;
        }
        if (!seen_double_dash && arg[0] == '-' && !(strcmp(arg, "-") == 0)) {
            // Already handled unknown options earlier.
            continue;
        }
        const char *path = arg; // operand
        // Determine parent directory.
        const char *slash = strrchr(path, '/');
        char parent[PATH_MAX];
        if (slash == NULL) {
            strcpy(parent, ".");
        } else if (slash == path) { // root like "/foo"
            // Parent is "/"
            strncpy(parent, "/", sizeof(parent)-1);
            parent[sizeof(parent)-1] = '\0';
        } else {
            size_t len = slash - path;
            if (len >= sizeof(parent)) {
                // Truncate safely; unlikely.
                len = sizeof(parent) - 1;
            }
            memcpy(parent, path, len);
            parent[len] = '\0';
        }

        struct stat st;
        // Verify parent exists and is a directory.
        if (stat(parent, &st) != 0) {
            print_error(path, strerror(errno));
            any_failure = 1;
            continue;
        }
        if (!S_ISDIR(st.st_mode)) {
            print_error(path, "Not a directory");
            any_failure = 1;
            continue;
        }

        // Check whether final component already exists.
        if (stat(path, &st) == 0) {
            print_error(path, "File exists");
            any_failure = 1;
            continue;
        } else if (errno != ENOENT) { // some other error accessing the path
            print_error(path, strerror(errno));
            any_failure = 1;
            continue;
        }

        // Attempt to create directory with default mode.
        if (mkdir(path, 0777) != 0) {
            print_error(path, strerror(errno));
            any_failure = 1;
            continue;
        }
    }

    return any_failure ? 1 : 0;
}
