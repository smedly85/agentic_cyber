#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <errno.h>
#include <unistd.h>

static void report_error(const char *path, const char *msg) {
    fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, msg);
}

int main(int argc, char *argv[]) {
    int exit_status = 0;
    int have_operand = 0;
    int end_of_options = 0; // flag after '--' encountered
    for (int i = 1; i < argc; ++i) {
        const char *arg = argv[i];
        if (!end_of_options && strcmp(arg, "--") == 0) {
            // End of options marker – subsequent arguments are operands even if they start with '-'.
            end_of_options = 1;
            continue;
        }
        // Detect unknown options only before '--' is seen.
        if (!end_of_options && arg[0] == '-' && !(strcmp(arg, "-") == 0)) {
            fprintf(stderr,
                "mkdir: unrecognized option '%s'\n"
                "Try 'mkdir --help' for more information.\n",
                arg);
            return 1;
        }
        have_operand = 1;
        // Strip trailing slashes for uniform handling.
        size_t len = strlen(arg);
        while (len > 0 && arg[len - 1] == '/') {
            --len;
        }
        char *path = strndup(arg, len);
        if (!path) {
            fprintf(stderr, "%s\n", "memory allocation failure");
            return 1;
        }
        // Determine parent directory.
        char *slash = strrchr(path, '/');
        const char *parent;
        if (slash) {
            *slash = '\0';
            parent = (*path == '\0') ? "." : path; // "//foo" yields empty before slash -> treat as root? Simplify.
        } else {
            parent = ".";
        }
        struct stat st;
        if (stat(parent, &st) != 0) {
            report_error(arg, strerror(errno));
            exit_status = 1;
            free(path);
            continue;
        }
        if (!S_ISDIR(st.st_mode)) {
            report_error(arg, "Not a directory");
            exit_status = 1;
            free(path);
            continue;
        }
        // Check final component existence.
        struct stat dummy;
        if (lstat(arg, &dummy) == 0) {
            report_error(arg, "File exists");
            exit_status = 1;
            free(path);
            continue;
        }
        // Attempt to create directory.
        if (mkdir(arg, 0777) != 0) {
            report_error(arg, strerror(errno));
            exit_status = 1;
            free(path);
            continue;
        }
        free(path);
    }
    if (!have_operand) {
        fprintf(stderr,
            "mkdir: missing operand\n"
            "Try 'mkdir --help' for more information.\n");
        return 1;
    }
    return exit_status;
}
