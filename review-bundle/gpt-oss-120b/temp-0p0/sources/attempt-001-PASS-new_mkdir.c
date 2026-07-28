#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <errno.h>

static void report_failure(const char *path, const char *msg) {
    fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, msg);
}

int main(int argc, char *argv[]) {
    int i = 1;
    int any_failed = 0;
    int have_operand = 0;

    // Skip program name; parse options (none defined yet)
    for (; i < argc; ++i) {
        const char *arg = argv[i];
        if (strcmp(arg, "--") == 0) {
            ++i; // skip the marker and stop option processing
            break;
        }
        if (arg[0] == '-' && strcmp(arg, "-") != 0) {
            // unknown option
            fprintf(stderr, "mkdir: unrecognized option '%s'\nTry 'mkdir --help' for more information.\n", arg);
            return 1;
        }
        break; // first non-option argument
    }

    // Remaining arguments from i to argc-1 are operands
    for (; i < argc; ++i) {
        const char *path = argv[i];
        have_operand = 1;
        /* Split into parent and final component */
        char *copy = strdup(path);
        if (!copy) {
            fprintf(stderr, "mkdir: memory allocation failed\n");
            return 1;
        }
        // Remove any trailing slashes from the operand (except when the path is just "/")
        size_t len = strlen(copy);
        while (len > 1 && copy[len - 1] == '/') {
            copy[--len] = '\0';
        }
        char *parent = NULL;
        char *slash = strrchr(copy, '/');
        if (slash) {
            *slash = '\0';
            parent = copy; // may be empty string meaning current dir
        } else {
            parent = "."; // current directory
        }
        /* Verify parent exists and is a directory */
        struct stat st;
        if (stat(parent, &st) != 0) {
            report_failure(path, strerror(errno));
            any_failed = 1;
            free(copy);
            continue;
        }
        if (!S_ISDIR(st.st_mode)) {
            report_failure(path, "Not a directory");
            any_failed = 1;
            free(copy);
            continue;
        }
        /* Check if final component already exists */
        struct stat dummy;
        if (stat(path, &dummy) == 0) {
            report_failure(path, "File exists");
            any_failed = 1;
            free(copy);
            continue;
        }
        /* Attempt to create directory */
        if (mkdir(path, 0777) != 0) {
            report_failure(path, strerror(errno));
            any_failed = 1;
            free(copy);
            continue;
        }
        free(copy);
    }

    if (!have_operand) {
        fprintf(stderr, "mkdir: missing operand\nTry 'mkdir --help' for more information.\n");
        return 1;
    }

    return any_failed ? 1 : 0;
}
