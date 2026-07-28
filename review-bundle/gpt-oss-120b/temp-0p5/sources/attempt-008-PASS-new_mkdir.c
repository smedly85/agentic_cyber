#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <errno.h>
#include <libgen.h> // for dirname, basename (POSIX)
#include <unistd.h>

// Helper to print error messages in the required format.
static void report_error(const char *path, const char *msg) {
    fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, msg);
}

int main(int argc, char *argv[]) {
    // Parse arguments: recognize '--' and unknown options.
    int have_operand = 0;
    int exit_status = 0; // 0 if all succeed, 1 if any fail.
    for (int i = 1; i < argc; ++i) {
        char *arg = argv[i];
        // Handle '--' termination marker.
        if (strcmp(arg, "--") == 0) {
            // All following arguments are operands even if they start with '-'.
            for (int j = i + 1; j < argc; ++j) {
                have_operand = 1;
                char *operand = argv[j];
                // Process operand.
                // Duplicate string because dirname/basename may modify it.
                char *path_copy = strdup(operand);
                if (!path_copy) {
                    report_error(operand, "memory allocation failed");
                    exit_status = 1;
                    continue;
                }
                char *parent = dirname(path_copy);
                // Need another copy for basename since dirname may have altered it.
                char *base_copy = strdup(operand);
                if (!base_copy) {
                    free(path_copy);
                    report_error(operand, "memory allocation failed");
                    exit_status = 1;
                    continue;
                }


                // Check parent existence and that it is a directory.
                struct stat st;
                if (stat(parent, &st) != 0) {
                    report_error(operand, strerror(errno));
                    exit_status = 1;
                } else if (!S_ISDIR(st.st_mode)) {
                    report_error(operand, "Not a directory");
                    exit_status = 1;
                } else {
                    // Parent exists and is a directory; attempt mkdir.
                    if (mkdir(operand, 0777) != 0) {
                        report_error(operand, strerror(errno));
                        exit_status = 1;
                    }
                }
                free(path_copy);
                free(base_copy);
            }
            // After processing '--' and the rest, we are done.
            goto finish;
        }
        // If argument starts with '-' (and is not just "-"), it's an unknown option.
        if (arg[0] == '-' && !(strcmp(arg, "-") == 0)) {
            fprintf(stderr, "mkdir: unrecognized option '%s'\nTry 'mkdir --help' for more information.\n", arg);
            return 1;
        }
        // Otherwise treat as operand.
        have_operand = 1;
        char *operand = arg;
        // Duplicate for dirname/basename processing.
        char *path_copy = strdup(operand);
        if (!path_copy) {
            report_error(operand, "memory allocation failed");
            exit_status = 1;
            continue;
        }
        char *parent = dirname(path_copy);
        char *base_copy = strdup(operand);
        if (!base_copy) {
            free(path_copy);
            report_error(operand, "memory allocation failed");
            exit_status = 1;
            continue;
        }


        struct stat st;
        if (stat(parent, &st) != 0) {
            report_error(operand, strerror(errno));
            exit_status = 1;
        } else if (!S_ISDIR(st.st_mode)) {
            report_error(operand, "Not a directory");
            exit_status = 1;
        } else {
            // Parent exists and is dir; attempt mkdir.
            if (mkdir(operand, 0777) != 0) {
                report_error(operand, strerror(errno));
                exit_status = 1;
            }
        }
        free(path_copy);
        free(base_copy);
    }

        if (!have_operand) {
            fprintf(stderr, "mkdir: missing operand\nTry 'mkdir --help' for more information.\n");
            return 1;
        }
finish:
    return exit_status;
}
