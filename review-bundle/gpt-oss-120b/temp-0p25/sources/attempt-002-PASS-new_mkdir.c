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
#include <limits.h>

/* Helper: print error message to stderr in the required format */
static void perr(const char *path) {
    // Print error in the format required by tests.
    // Use errno set appropriately before calling this function.
    fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
}

int main(int argc, char *argv[]) {
    int exit_status = 0;
    int end_of_options = 0; // true after encountering '--'
    int operand_count = 0;

    // First pass: validate options and count operands
    for (int i = 1; i < argc; ++i) {
        const char *arg = argv[i];
        if (!end_of_options && strcmp(arg, "--") == 0) {
            end_of_options = 1;
            continue;
        }
        if (!end_of_options && arg[0] == '-' && strcmp(arg, "-") != 0) {
            // Unknown option
            fprintf(stderr, "mkdir: unrecognized option '%s'\n", arg);
            fprintf(stderr, "Try 'mkdir --help' for more information.\n");
            return 1;
        }
        ++operand_count; // every other token is an operand
    }
    if (operand_count == 0) {
        fprintf(stderr, "mkdir: missing operand\n");
        fprintf(stderr, "Try 'mkdir --help' for more information.\n");
        return 1;
    }

    // Second pass: process each operand
    end_of_options = 0; // reset for second traversal
    for (int i = 1; i < argc; ++i) {
        const char *orig_arg = argv[i];
        if (!end_of_options && strcmp(orig_arg, "--") == 0) {
            end_of_options = 1;
            continue;
        }
        if (!end_of_options && orig_arg[0] == '-' && strcmp(orig_arg, "-") != 0) {
            // should not happen after first pass validation
            continue;
        }
        // Normalize path: strip trailing slashes (except keep root "/")
        char arg[PATH_MAX];
        strncpy(arg, orig_arg, PATH_MAX - 1);
        arg[PATH_MAX - 1] = '\0';
        size_t len = strlen(arg);
        while (len > 1 && arg[len-1] == '/') {
            arg[--len] = '\0';
        }

        // Determine parent directory component
        const char *slash = strrchr(arg, '/');
        char parent[PATH_MAX];
        if (slash) {
            size_t plen = slash - arg; // characters before last '/'
            if (plen == 0) {
                strcpy(parent, "/");
            } else {
                memcpy(parent, arg, plen);
                parent[plen] = '\0';
            }
        } else {
            strcpy(parent, ".");
        }

        struct stat st;
        if (stat(parent, &st) != 0) { // parent does not exist
            perr(arg);
            exit_status = 1;
            continue;
        }
        if (!S_ISDIR(st.st_mode)) { // parent exists but is not a directory
            errno = ENOTDIR; // set appropriate error code for message
            perr(arg);
            exit_status = 1;
            continue;
        }
        // Check whether the target already exists
        struct stat dummy;
        if (stat(arg, &dummy) == 0) {
            errno = EEXIST; // set error for message
            perr(arg);
            exit_status = 1;
            continue;
        }
        // Attempt to create the directory with default mode (umask applied)
        if (mkdir(arg, 0777) != 0) {
            perr(arg);
            exit_status = 1;
            continue;
        }
    }
    return exit_status;
}
