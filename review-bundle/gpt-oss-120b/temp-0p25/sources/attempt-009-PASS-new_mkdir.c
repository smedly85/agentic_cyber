#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <limits.h>
#include <errno.h>

/*
 * new_mkdir – minimal mkdir implementation for the base checkpoint.
 * Supports only operand handling, '--' termination and unknown‑option detection.
 * For each operand it validates that the parent directory exists and is a directory,
 * that the final component does not already exist, and then attempts to create the
 * directory with mode 0777 (subject to the process umask).
 */

static void print_error(const char *path, const char *msg) {
    fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, msg);
}

int main(int argc, char *argv[]) {
        if (argc < 2) {
            /* No arguments at all */
            fprintf(stderr, "mkdir: missing operand\nTry 'mkdir --help' for more information.\n");
            return 1;
        }


    int end_of_options = 0;
    int operand_count = 0;
    int overall_success = 1;   // assume success until a failure occurs

    for (int i = 1; i < argc; ++i) {
        char *arg = argv[i];
        if (!end_of_options && strcmp(arg, "--") == 0) {
            end_of_options = 1;
            continue;
        }
        if (!end_of_options && arg[0] == '-' && !(strcmp(arg, "-") == 0)) {
            /* Unknown option */
            // Match GNU mkdir error format for unrecognized options
            fprintf(stderr, "mkdir: unrecognized option '%s'\nTry 'mkdir --help' for more information.\n", arg);
            return 1;
        }

        /* Treat as operand */
        ++operand_count;
        const char *orig_path = arg;
        /* Remove trailing slashes for consistency (except when the path is just "/") */
        size_t orig_len = strlen(orig_path);
        while (orig_len > 1 && orig_path[orig_len - 1] == '/') {
            orig_len--;
        }
        char path[PATH_MAX];
        if (orig_len >= sizeof(path)) {
            /* Path too long; let later mkdir fail with ENAMETOOLONG */
            strncpy(path, orig_path, sizeof(path) - 1);
            path[sizeof(path) - 1] = '\0';
        } else {
            memcpy(path, orig_path, orig_len);
            path[orig_len] = '\0';
        }

        /* Split path into parent and final component */
        const char *slash = strrchr(path, '/');
        char parent[PATH_MAX];
        if (slash == NULL) {
            strcpy(parent, ".");
        } else {
            size_t len = slash - path;
            if (len == 0) { /* path like "/foo" where parent is '/' */
                strncpy(parent, "/", sizeof(parent)-1);
                parent[sizeof(parent)-1] = '\0';
            } else {
                if (len >= sizeof(parent)) len = sizeof(parent)-1;
                memcpy(parent, path, len);
                parent[len] = '\0';
            }
        }

        struct stat sb;
        /* Verify parent exists and is a directory */
        if (stat(parent, &sb) != 0) {
            print_error(path, strerror(errno));
            overall_success = 0;
            continue;
        }
        if (!S_ISDIR(sb.st_mode)) {
            print_error(path, "Not a directory");
            overall_success = 0;
            continue;
        }

        /* Check if final component already exists */
        struct stat dummy;
        if (stat(path, &dummy) == 0) {
            print_error(path, "File exists");
            overall_success = 0;
            continue;
        }

        /* Attempt to create the directory */
        if (mkdir(path, 0777) != 0) {
            print_error(path, strerror(errno));
            overall_success = 0;
            continue;
        }
    }

    if (operand_count == 0) {
        fprintf(stderr, "missing operand\n");
        return 1;
    }

    return overall_success ? 0 : 1;
}
