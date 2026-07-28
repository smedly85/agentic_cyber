/*
 * new_mkdir – minimal directory creation utility.
 * Implements the behavior described in the task prompt.
 */

#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/stat.h>
#include <unistd.h>

/* Helper: print error message to stderr in the required format */
static void perr(const char *path) {
    fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
}

int main(int argc, char *argv[]) {
    int exit_status = 0;
    int i = 1;                // index over argv
    int end_of_options = 0;   // set after encountering '--'
    /* Collect operands */
    for (; i < argc; ++i) {
        const char *arg = argv[i];
        if (!end_of_options && strcmp(arg, "--") == 0) { // stop option parsing
            end_of_options = 1;
            continue;
        }
        if (!end_of_options && arg[0] == '-' && !(strcmp(arg, "-") == 0)) {
            /* Unknown option */
            fprintf(stderr, "%s: unrecognized option '%s'\n", argv[0], arg);
            return 1;
        }
        /* Treat as operand */
        // Determine parent directory
        const char *slash = strrchr(arg, '/');
        char parent[PATH_MAX];
        if (slash) {
            size_t len = slash - arg; // length of parent path
            if (len == 0) { // leading '/' -> root
                strcpy(parent, "/");
            } else {
                memcpy(parent, arg, len);
                parent[len] = '\0';
            }
        } else {
            strcpy(parent, ".");
        }
        struct stat st;
        if (stat(parent, &st) != 0) { // parent missing
            perr(arg);
            exit_status = 1;
            continue;
        }
        if (!S_ISDIR(st.st_mode)) { // parent not a directory
            perr(arg);
            exit_status = 1;
            continue;
        }
        /* Check if final component already exists */
        struct stat st2;
        if (stat(arg, &st2) == 0) {
            errno = EEXIST; // set appropriate error for message
            perr(arg);
            exit_status = 1;
            continue;
        }
        /* Attempt to create directory */
        if (mkdir(arg, 0777) != 0) {
            perr(arg);
            exit_status = 1;
            continue;
        }
    }
    if (!end_of_options && argc == 1) { // no arguments at all
        fprintf(stderr, "%s: missing operand\n", argv[0]);
        return 1;
    }
    /* If we have processed arguments but none were operands (e.g., only '--') */
    if (i == argc && !end_of_options) {
        // already handled above
    }
    return exit_status;
}
