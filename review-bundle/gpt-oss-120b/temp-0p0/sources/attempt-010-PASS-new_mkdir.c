#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <errno.h>
#include <unistd.h>

static void print_error(const char *prog, const char *path) {
    // Use strerror to get human readable reason
    fprintf(stderr, "%s: cannot create directory '%s': %s\n", prog, path, strerror(errno));
}

int main(int argc, char *argv[]) {
    const char *prog_name = "mkdir";
    int i;
    int any_failure = 0;
    int have_operand = 0;
    int end_of_options = 0;
    // First pass: parse arguments, detect unknown options and collect operands
    for (i = 1; i < argc; ++i) {
        char *arg = argv[i];
        if (!end_of_options && strcmp(arg, "--") == 0) {
            end_of_options = 1;
            continue;
        }
        if (!end_of_options && arg[0] == '-' && !(strcmp(arg, "-") == 0)) {
            // Unknown option
            fprintf(stderr, "%s: unrecognized option '%s'\nTry '%s --help' for more information.\n", prog_name, arg, prog_name);
            return 1;
        }
        // Operand (could be "-" or any other string)
        have_operand = 1;
        // Make a mutable copy because we may need to trim trailing slashes
        char *path_copy = strdup(arg);
        if (!path_copy) {
            fprintf(stderr, "%s: memory allocation failed\n", prog_name);
            return 1;
        }
        size_t len = strlen(path_copy);
        // Trim trailing '/' characters (but keep a single '/' if the path is root)
        while (len > 1 && path_copy[len - 1] == '/') {
            path_copy[--len] = '\0';
        }
        // Determine parent directory
        char *slash = strrchr(path_copy, '/');
        const char *parent;
        if (slash) {
            // Temporarily terminate string to isolate parent part
            *slash = '\0';
            parent = (*path_copy == '\0') ? "/" : path_copy; // handle leading '/' case like "/dir"
        } else {
            parent = ".";
        }
        // Check that parent exists and is a directory
        struct stat st;
        if (stat(parent, &st) != 0) {
            // Parent does not exist or cannot be accessed
            errno = ENOENT; // Ensure reason matches GNU mkdir style for missing component
            print_error(prog_name, arg);
            any_failure = 1;
            free(path_copy);
            continue;
        }
        if (!S_ISDIR(st.st_mode)) {
            errno = ENOTDIR;
            print_error(prog_name, arg);
            any_failure = 1;
            free(path_copy);
            continue;
        }
        // Check if the final component already exists
        struct stat dummy;
        if (stat(arg, &dummy) == 0) {
            errno = EEXIST;
            print_error(prog_name, arg);
            any_failure = 1;
            free(path_copy);
            continue;
        }
        // Attempt to create the directory with default mode (umask applied)
        if (mkdir(arg, 0777) != 0) {
            // errno already set by mkdir
            print_error(prog_name, arg);
            any_failure = 1;
            free(path_copy);
            continue;
        }
        free(path_copy);
    }
    if (!have_operand) {
        fprintf(stderr, "%s: missing operand\nTry '%s --help' for more information.\n", prog_name, prog_name);
        return 1;
    }
    return any_failure ? 1 : 0;
}
