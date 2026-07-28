#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/stat.h>
#include <unistd.h>

/*
 * new_mkdir – create directories specified as operands.
 * Implements the behavior described in the task specification for checkpoint 1.
 */

static int report_error(const char *path, const char *msg) {
    fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, msg);
    return 1;
}

int main(int argc, char *argv[]) {
    if (argc == 1) {
        // No operands at all.
        fprintf(stderr, "mkdir: missing operand\nTry 'mkdir --help' for more information.\n");
        return 1;
    }

    int exit_status = 0; // 0 if all succeed, otherwise 1
    int i = 1;
    // Parse options (only '--' is recognized)
    while (i < argc) {
        char *arg = argv[i];
        if (strcmp(arg, "--") == 0) { // end of options marker
            i++; // skip the '--'
            break; // remaining arguments are operands
        }
        if (arg[0] == '-' && !(strcmp(arg, "-") == 0)) {
            // Unknown option before '--'
            fprintf(stderr, "mkdir: unrecognized option '%s'\nTry 'mkdir --help' for more information.\n", arg);
            return 1;
        }
        // first non-option encountered without '--', treat as operand start
        break;
    }

    // Process remaining arguments as operands.
    for (; i < argc; ++i) {
        char *orig_path = argv[i];
        if (strcmp(orig_path, "--") == 0) continue; // skip stray '--' after processing start
        // After '--', leading '-' is allowed as operand name. So do not treat as option.
        // However, if we haven't seen '--' yet and encounter an unknown option, it's already handled above.
        char *path = orig_path;
        // Strip trailing slashes (except when path is just "/")
        size_t len = strlen(path);
        while (len > 1 && path[len-1] == '/') {
            ((char *)path)[len-1] = '\0';
            len--;
        }

        /* Determine parent directory */
        char *slash = strrchr(path, '/');
        if (slash != NULL) {
            // There is a directory component.
            size_t parent_len = slash - path; // length of parent part
            char parent[parent_len + 1];
            memcpy(parent, path, parent_len);
            parent[parent_len] = '\0';

            struct stat sb;
            if (stat(parent, &sb) != 0) {
                // Parent does not exist or cannot be accessed.
                exit_status = report_error(path, strerror(errno));
                continue;
            }
            if (!S_ISDIR(sb.st_mode)) {
                // Parent exists but is not a directory.
                exit_status = report_error(path, "Not a directory");
                continue;
            }
        } else {
            // No slash – parent is current directory, which always exists for our purposes.
            ; // nothing to check
        }

        /* Check if the final component already exists */
        struct stat sb2;
        if (lstat(path, &sb2) == 0) {
            // Something with that name already exists.
            exit_status = report_error(path, "File exists");
            continue;
        }

        /* Attempt to create the directory */
        if (mkdir(path, 0777) != 0) {
            // mkdir failed – use errno message.
            exit_status = report_error(path, strerror(errno));
            continue;
        }
    }

    return exit_status;
}
