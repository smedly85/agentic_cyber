#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/stat.h>
#include <sys/types.h>

/*
 * new_mkdir – create directories specified on the command line.
 * Implements the minimal behavior required for the first checkpoint.
 */

static void report_error(const char *path, const char *msg)
{
    fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, msg);
}

int main(int argc, char *argv[])
{
    int any_failure = 0;
    int have_operand = 0;
    int options_done = 0; // true after encountering "--"

    for (int i = 1; i < argc; ++i) {
        const char *arg = argv[i];

        if (!options_done) {
            if (strcmp(arg, "--") == 0) {
                options_done = 1;
                continue;
            }
            if (arg[0] == '-' && strcmp(arg, "-") != 0) { // unknown option
                fprintf(stderr, "mkdir: unrecognized option '%s'\nTry 'mkdir --help' for more information.\n", arg);
                return 1;
            }
        }

        /* From here on every argument is an operand */
        have_operand = 1;
        const char *orig_path = arg;

        // Strip trailing '/' characters (except when the path is just "/")
        size_t len = strlen(orig_path);
        while (len > 1 && orig_path[len - 1] == '/') {
            --len;
        }
        char *path = strndup(orig_path, len);
        if (!path) {
            fprintf(stderr, "new_mkdir: memory allocation failed\n");
            return 1;
        }

        // Find parent directory and final component
        char *slash = strrchr(path, '/');
        const char *parent_dir;
        if (slash) {
            // Split in place
            *slash = '\0';
            parent_dir = (*path == '\0') ? "/" : path; // handle leading '/' e.g. "/foo"
            // final component is after slash, already stored elsewhere for error messages
        } else {
            parent_dir = ".";
        }

        struct stat st;
        if (stat(parent_dir, &st) != 0) {
            report_error(orig_path, strerror(errno));
            any_failure = 1;
            free(path);
            continue;
        }
        if (!S_ISDIR(st.st_mode)) {
            report_error(orig_path, "Not a directory");
            any_failure = 1;
            free(path);
            continue;
        }

        // Check whether the target already exists
        if (stat(orig_path, &st) == 0) {
            report_error(orig_path, "File exists");
            any_failure = 1;
            free(path);
            continue;
        }

        // Attempt to create directory with mode 0777 (umask applied by OS)
        if (mkdir(orig_path, 0777) != 0) {
            report_error(orig_path, strerror(errno));
            any_failure = 1;
            free(path);
            continue;
        }

        free(path);
    }

    if (!have_operand) {
        fprintf(stderr, "mkdir: missing operand\nTry 'mkdir --help' for more information.\n");
        return 1;
    }

    return any_failure ? 1 : 0;
}
