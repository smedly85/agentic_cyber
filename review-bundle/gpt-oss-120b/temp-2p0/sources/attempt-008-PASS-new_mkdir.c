#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/stat.h>
#include <unistd.h>
#include <stdbool.h>

static void print_error(const char *path, const char *msg) {
    fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, msg);
}

int main(int argc, char *argv[]) {
    // Handle missing operand case with GNU‑style message
    if (argc == 1) {
        fprintf(stderr, "mkdir: missing operand\nTry 'mkdir --help' for more information.\n");
        return 1;
    }

    int any_failure = 0;
    bool end_of_options = false; // track '--'
    for (int i = 1; i < argc; ++i) {
        char *arg = argv[i];
        if (!end_of_options && strcmp(arg, "--") == 0) {
            end_of_options = true;
            continue; // marker not an operand
        }
        // Unknown option handling (only before '--' and not a bare '-')
        if (!end_of_options && arg[0] == '-' && strcmp(arg, "-") != 0) {
            fprintf(stderr,
                    "mkdir: unrecognized option '%s'\nTry 'mkdir --help' for more information.\n",
                    arg);
            return 1;
        }

        // Preserve original argument for error messages
        const char *orig = arg;
        // Strip trailing slashes for processing (but keep original for messages)
        size_t len = strlen(arg);
        while (len > 0 && arg[len - 1] == '/') {
            arg[len - 1] = '\0';
            len--;
        }
        if (len == 0) { // argument was only '/' characters
            // treat as root which already exists – nothing to create, report error like existing
            print_error(orig, "File exists");
            any_failure = 1;
            continue;
        }

        // Determine parent path
        char *sep = strrchr(arg, '/');
        char *parent;
        if (sep) {
            size_t plen = sep - arg;
            if (plen == 0) {
                parent = strdup("/");
            } else {
                parent = malloc(plen + 1);
                if (!parent) { perror("malloc"); return 1; }
                memcpy(parent, arg, plen);
                parent[plen] = '\0';
            }
        } else {
            parent = strdup(".");
            if (!parent) { perror("strdup"); return 1; }
        }

        // Verify parent exists and is a directory
        struct stat st;
        if (stat(parent, &st) != 0) {
            print_error(orig, strerror(errno));
            any_failure = 1;
            free(parent);
            continue;
        }
        if (!S_ISDIR(st.st_mode)) {
            print_error(orig, "Not a directory");
            any_failure = 1;
            free(parent);
            continue;
        }

        // Ensure final component does not already exist
        struct stat st2;
        if (stat(arg, &st2) == 0) {
            print_error(orig, "File exists");
            any_failure = 1;
            free(parent);
            continue;
        }

        // Create directory with default permissions (umask applied)
        if (mkdir(arg, 0777) != 0) {
            print_error(orig, strerror(errno));
            any_failure = 1;
            free(parent);
            continue;
        }

        free(parent);
    }

    return any_failure ? 1 : 0;
}
