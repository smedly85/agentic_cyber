#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <limits.h>
#include <sys/stat.h>
#include <unistd.h>

static int report_error(const char *path, const char *msg) {
    fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, msg);
    return 1;
}

int main(int argc, char *argv[]) {
    if (argc <= 1) {
        fprintf(stderr, "mkdir: missing operand\nTry 'mkdir --help' for more information.\n");
        return 1;
    }

    int any_failure = 0;
    int end_of_options = 0; // true after seeing "--"
    for (int i = 1; i < argc; ++i) {
        char *arg = argv[i];
        if (!end_of_options && strcmp(arg, "--") == 0) {
            end_of_options = 1;
            continue; // "--" is not an operand
        }
        int is_operand = end_of_options || arg[0] != '-';
        if (!is_operand) {
            /* Unknown option */
            fprintf(stderr, "mkdir: unrecognized option '%s'\nTry 'mkdir --help' for more information.\n", arg);
            return 1;
        }
        // Treat a lone '-' as an operand (still a path)
        const char *original_path = arg; // preserve for messages
        // Make a mutable copy to strip trailing slashes for processing
        char path_buf[PATH_MAX];
        strncpy(path_buf, arg, PATH_MAX - 1);
        path_buf[PATH_MAX - 1] = '\0';
        size_t len = strlen(path_buf);
        while (len > 1 && path_buf[len-1] == '/') {
            path_buf[--len] = '\0';
        }
        const char *path = path_buf;

        /* Determine parent directory */
        char *sep = strrchr(path, '/');
        char parent[PATH_MAX];
        if (sep) {
            size_t plen = sep - path; // length of parent part
            if (plen == 0) {
                // Path like "/name" – parent is root "/"
                strcpy(parent, "/");
            } else {
                if (plen >= sizeof(parent)) {
                    any_failure = report_error(original_path, "path too long");
                    continue;
                }
                memcpy(parent, path, plen);
                parent[plen] = '\0';
            }
        } else {
            // No slash – parent is current directory "."
            strcpy(parent, ".");
        }

        /* Verify parent exists and is a directory */
        struct stat sb;
        if (stat(parent, &sb) != 0) {
            any_failure = report_error(original_path, strerror(errno));
            continue;
        }
        if (!S_ISDIR(sb.st_mode)) {
            any_failure = report_error(original_path, "Not a directory");
            continue;
        }

        /* Check that the final component does not already exist */
        struct stat dummy;
        if (lstat(original_path, &dummy) == 0) {
            any_failure = report_error(original_path, "File exists");
            continue;
        } else if (errno != ENOENT) {
            any_failure = report_error(original_path, strerror(errno));
            continue;
        }

        /* Attempt to create the directory */
        if (mkdir(path, 0777) != 0) {
            any_failure = report_error(original_path, strerror(errno));
            continue;
        }
        // Success – nothing to output.
    }
    return any_failure ? 1 : 0;
}
