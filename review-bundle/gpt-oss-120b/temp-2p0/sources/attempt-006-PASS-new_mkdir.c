#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <errno.h>
#include <libgen.h>

/*
 * new_mkdir – create directories specified as operands.
 * Implements the minimal behavior described in the task prompt.
 */

static int report_error(const char *path, const char *msg) {
    fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, msg);
    return 1;
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        fprintf(stderr, "mkdir: missing operand\nTry 'mkdir --help' for more information.\n");
        return 1;
    }

    int status = 0; // overall success flag (0 if all succeed)
    int parsing_options = 1; // true until '--' encountered
    for (int i = 1; i < argc; ++i) {
        char *arg = argv[i];
        if (strcmp(arg, "--") == 0) {
            parsing_options = 0;
            continue; // skip the marker itself
        }
        if (parsing_options && arg[0] == '-' && strcmp(arg, "-") != 0) {
            fprintf(stderr, "mkdir: unrecognized option '%s'\nTry 'mkdir --help' for more information.\n", arg);
            return 1;
        }
        /* Process operand */
        // Determine parent directory
        char *path_copy = strdup(arg);
        if (!path_copy) {
            perror("strdup");
            return 1;
        }
        // To find parent, we need a separate copy because dirname may modify.
        char *parent_copy = strdup(arg);
        if (!parent_copy) {
            free(path_copy);
            perror("strdup");
            return 1;
        }
        char *dir = dirname(parent_copy);
        // Check parent existence and that it is a directory
        struct stat st;
        if (stat(dir, &st) != 0) {
            report_error(arg, strerror(errno));
            status = 1;
            free(path_copy);
            free(parent_copy);
            continue;
        }
        if (!S_ISDIR(st.st_mode)) {
            report_error(arg, "Not a directory");
            status = 1;
            free(path_copy);
            free(parent_copy);
            continue;
        }
        // Check if final component already exists
        struct stat st2;
        if (lstat(arg, &st2) == 0) {
            report_error(arg, "File exists");
            status = 1;
            free(path_copy);
            free(parent_copy);
            continue;
        }
        // Attempt to create directory
        if (mkdir(arg, 0777) != 0) {
            report_error(arg, strerror(errno));
            status = 1;
            free(path_copy);
            free(parent_copy);
            continue;
        }
        // Success – clean up
        free(path_copy);
        free(parent_copy);
    }
    return status;
}
