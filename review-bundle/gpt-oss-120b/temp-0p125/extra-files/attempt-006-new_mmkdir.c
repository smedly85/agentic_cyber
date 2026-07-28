#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/stat.h>
#include <unistd.h>

int main(int argc, char *argv[]) {
    int any_failure = 0;
    int operand_count = 0;
    int parsing_options = 1; // true before encountering "--"

    for (int i = 1; i < argc; ++i) {
        char *arg = argv[i];
        if (parsing_options) {
            if (strcmp(arg, "--") == 0) {
                parsing_options = 0;
                continue;
            }
            if (arg[0] == '-' && strcmp(arg, "-") != 0) {
                // Unknown option
                fprintf(stderr, "new_mkdir: unrecognized option '%s'\n", arg);
                return 1;
            }
        }
        // Treat as operand
        ++operand_count;
        const char *path = arg; // keep original for messages

        // Duplicate path so we can modify it safely (remove trailing slashes)
        char *dup = strdup(path);
        if (!dup) {
            fprintf(stderr, "new_mkdir: memory allocation failed\n");
            return 1;
        }
        size_t len = strlen(dup);
        while (len > 1 && dup[len - 1] == '/') {
            dup[--len] = '\0';
        }

        // Determine parent directory
        char *slash = strrchr(dup, '/');
        const char *parent;
        if (slash) {
            if (slash == dup) { // path like "/foo"
                parent = "/";
                // leave duplicate as is for later; final component after slash will be handled by mkdir directly
            } else {
                *slash = '\0';
                parent = dup; // points to beginning of string up to last '/'
            }
        } else {
            parent = ".";
        }

        struct stat st_parent;
        if (stat(parent, &st_parent) != 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
            any_failure = 1;
            free(dup);
            continue;
        }
        if (!S_ISDIR(st_parent.st_mode)) {
            fprintf(stderr, "mkdir: cannot create directory '%s': Not a directory\n", path);
            any_failure = 1;
            free(dup);
            continue;
        }

        // Check whether final component already exists
        struct stat st_target;
        if (stat(path, &st_target) == 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': File exists\n", path);
            any_failure = 1;
            free(dup);
            continue;
        }

        // Attempt to create the directory with default mode (umask applied automatically)
        if (mkdir(path, 0777) != 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
            any_failure = 1;
        }

        free(dup);
    }

    if (operand_count == 0) {
        fprintf(stderr, "new_mkdir: missing operand\n");
        return 1;
    }

    return any_failure ? 1 : 0;
}
