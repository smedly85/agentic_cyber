#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/stat.h>
#include <unistd.h>
#include <limits.h>

int main(int argc, char *argv[]) {
    int any_error = 0;
    int end_of_options = 0;
    int operand_count = 0;
    // First pass: count operands and detect early errors.
    const char *progname = "mkdir"; // program name for error messages
    for (int i = 1; i < argc; ++i) {
        char *arg = argv[i];
        if (!end_of_options && strcmp(arg, "--") == 0) {
            end_of_options = 1;
            continue;
        }
        if (!end_of_options && arg[0] == '-' && !(strcmp(arg, "-") == 0)) {
            // Unknown option
            fprintf(stderr, "%s: unrecognized option '%s'\n", progname, arg);
            fprintf(stderr, "Try 'mkdir --help' for more information.\n");
            return 1;
        }
        /* treat as operand */
        ++operand_count;
    }

    if (operand_count == 0) {
        fprintf(stderr, "%s: missing operand\n", progname);
        fprintf(stderr, "Try 'mkdir --help' for more information.\n");
        return 1;
    }

    // Reset parsing state for second pass to actually process operands.
    end_of_options = 0;
    for (int i = 1; i < argc; ++i) {
        char *arg = argv[i];
        if (!end_of_options && strcmp(arg, "--") == 0) {
            end_of_options = 1;
            continue;
        }
        if (!end_of_options && arg[0] == '-' && !(strcmp(arg, "-") == 0)) {
            // unknown option already handled earlier; skip
            continue;
        }
        /* Operand processing */
        const char *orig_path = arg; // keep for messages
        /* Normalize trailing slashes (except when the whole path is "/") */
        char norm_path[PATH_MAX];
        strncpy(norm_path, orig_path, PATH_MAX-1);
        norm_path[PATH_MAX-1] = '\0';
        size_t nlen = strlen(norm_path);
        while (nlen > 1 && norm_path[nlen-1] == '/') {
            norm_path[--nlen] = '\0';
        }
        const char *path = norm_path; // use normalized path for processing
        /* Determine parent directory */
        char parent_path[PATH_MAX];
        const char *slash = strrchr(path, '/');
        if (slash == NULL) {
            strcpy(parent_path, ".");
        } else if (slash == path) {
            // Path like "/foo" -> parent is "/"
            strcpy(parent_path, "/");
        } else {
            size_t plen = slash - path;
            if (plen >= sizeof(parent_path)) {
                errno = ENAMETOOLONG;
                fprintf(stderr, "%s: cannot create directory '%s': %s\n", progname, orig_path, strerror(errno));
                any_error = 1;
                continue;
            }
            strncpy(parent_path, path, plen);
            parent_path[plen] = '\0';
        }

        struct stat st;
        if (stat(parent_path, &st) != 0) {
            // Parent does not exist or cannot be accessed
            fprintf(stderr, "%s: cannot create directory '%s': %s\n", progname, orig_path, strerror(errno));
            any_error = 1;
            continue;
        }
        if (!S_ISDIR(st.st_mode)) {
            errno = ENOTDIR;
            fprintf(stderr, "%s: cannot create directory '%s': %s\n", progname, orig_path, strerror(errno));
            any_error = 1;
            continue;
        }

        /* Check if final component already exists */
        if (lstat(path, &st) == 0) {
            errno = EEXIST;
            fprintf(stderr, "%s: cannot create directory '%s': %s\n", progname, orig_path, strerror(errno));
            any_error = 1;
            continue;
        }

        /* Attempt to create */
        if (mkdir(path, 0777) != 0) {
            fprintf(stderr, "%s: cannot create directory '%s': %s\n", progname, orig_path, strerror(errno));
            any_error = 1;
            continue;
        }
    }

    return any_error ? 1 : 0;
}
