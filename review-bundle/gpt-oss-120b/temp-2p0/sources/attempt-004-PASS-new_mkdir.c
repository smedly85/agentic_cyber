#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <errno.h>

int main(int argc, char *argv[]) {
    int have_error = 0;
    int end_of_options = 0;
    // Collect operands after handling options.
    for (int i = 1; i < argc; ++i) {
        char *arg = argv[i];
        if (!end_of_options) {
            if (strcmp(arg, "--") == 0) { /* stop option parsing */
                end_of_options = 1;
                continue;
            }
            if (arg[0] == '-' && strcmp(arg, "-") != 0) {
                // Unknown option
                fprintf(stderr, "mkdir: unrecognized option '%s'\n", arg);
fprintf(stderr, "Try 'mkdir --help' for more information.\n");
                return 1;
            }
        }
        // At this point arg is an operand.
        if (arg[0] == '\0') continue; // skip empty strings just in case
        // Determine parent path and final component.
        char *path = arg;
        // Make a mutable copy because we will modify it to locate the last '/'.
                char *copy = strdup(path);
        if (!copy) {
            fprintf(stderr, "new_mkdir: memory allocation failed\n");
            return 1;
        }
        /* Strip trailing slashes (except when the path is just "/") */
        size_t len = strlen(copy);
        while (len > 1 && copy[len-1] == '/') {
            copy[--len] = '\0';
        }
        if (!copy) {
            fprintf(stderr, "new_mkdir: memory allocation failed\n");
            return 1;
        }
        char *parent;
        /* base component not needed for this checkpoint */
        char *slash = strrchr(copy, '/');
        if (slash) {
            // Split into parent and base.
            *slash = '\0';
            parent = (*copy == '\0') ? "." : copy; // leading '/' results in empty string before first slash
            // base not needed for this checkpoint
        } else {
            parent = ".";
            // base not needed for this checkpoint
        }
        // Check that parent exists and is a directory.
        struct stat st;
        if (stat(parent, &st) != 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
            have_error = 1;
            free(copy);
            continue;
        }
        if (!S_ISDIR(st.st_mode)) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(ENOTDIR));
            have_error = 1;
            free(copy);
            continue;
        }
        // Check if final component already exists.
        struct stat st2;
        if (stat(path, &st2) == 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(EEXIST));
            have_error = 1;
            free(copy);
            continue;
        }
        // Attempt to create the directory.
        if (mkdir(path, 0777) != 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
            have_error = 1;
            free(copy);
            continue;
        }
        // Success – nothing to output.
        free(copy);
    }

    // After processing all arguments, check for missing operand case.
    if (argc == 1) {
        fprintf(stderr, "mkdir: missing operand\nTry 'mkdir --help' for more information.\n");
        return 1;
    }

    return have_error ? 1 : 0;
}
