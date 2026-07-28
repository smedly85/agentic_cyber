#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/stat.h>
#include <unistd.h>

int main(int argc, char *argv[]) {
    int any_failure = 0;
    int operand_count = 0;
    int parsing_options = 1; // true until '--' is seen

    for (int i = 1; i < argc; ++i) {
        char *arg = argv[i];
        if (parsing_options) {
            if (strcmp(arg, "--") == 0) {
                parsing_options = 0;
                continue;
            }
            if (arg[0] == '-' && strcmp(arg, "-") != 0) { // unknown option
                fprintf(stderr, "mkdir: unrecognized option '%s'\nTry 'mkdir --help' for more information.\n", arg);
                return 1;
            }
        }
        ++operand_count; // treat as operand
        const char *path = arg; // keep original for messages

        // Make a mutable copy to strip trailing slashes
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
                *slash = '\0'; // make dup empty string for stat on ""
            } else {
                *slash = '\0';
                parent = dup; // parent part of the path
            }
        } else {
            parent = "."; // relative path, no slash
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

        // Check if target already exists
        struct stat st_target;
        if (stat(path, &st_target) == 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': File exists\n", path);
            any_failure = 1;
            free(dup);
            continue;
        }

        // Try to create the directory with default mode (umask applied)
        if (mkdir(path, 0777) != 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
            any_failure = 1;
        }

        free(dup);
    }

    if (operand_count == 0) {
        fprintf(stderr, "mkdir: missing operand\nTry 'mkdir --help' for more information.\n");
        return 1;
    }

    return any_failure ? 1 : 0;
}
