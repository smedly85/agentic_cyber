#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/stat.h>
#include <unistd.h>
#include <limits.h>

static void report_error(const char *path, const char *msg) {
    fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, msg);
}

int main(int argc, char *argv[]) {
    int any_failure = 0;
    int end_of_options = 0;
    int operand_count = 0;

    // First pass to collect operands and detect early errors.
    for (int i = 1; i < argc; i++) {
        const char *arg = argv[i];
        if (!end_of_options) {
            if (strcmp(arg, "--") == 0) { end_of_options = 1; continue; }
            if (arg[0] == '-' && !(strcmp(arg, "-") == 0)) {
                // Unknown option.
        fprintf(stderr, "mkdir: unrecognized option '%s'\nTry 'mkdir --help' for more information.\n", arg);
                return 1;
            }
        }
        // Treat as operand.
        operand_count++;
    }

    if (operand_count == 0) {
        fprintf(stderr, "mkdir: missing operand\nTry 'mkdir --help' for more information.\n");
        return 1;
    }

    // Second pass: actually process operands in order.
    end_of_options = 0; // reset for second scan
    for (int i = 1; i < argc; i++) {
        const char *arg = argv[i];
        if (!end_of_options) {
            if (strcmp(arg, "--") == 0) { end_of_options = 1; continue; }
            if (arg[0] == '-' && !(strcmp(arg, "-") == 0)) {
                // Already handled unknown option case; this path won't be reached.
                continue;
            }
        }
        /* Prepare operand path: strip trailing slashes for processing */
        const char *orig_path = arg;
        char path[PATH_MAX];
        strncpy(path, orig_path, PATH_MAX - 1);
        path[PATH_MAX - 1] = '\0';
        size_t lenp = strlen(path);
        while (lenp > 1 && path[lenp - 1] == '/') {
            path[--lenp] = '\0';
        }

        /* Determine parent directory of stripped path */
        const char *slash = strrchr(path, '/');
        char parent[PATH_MAX];
        if (slash) {
            size_t plen = slash - path; // length of parent part
            if (plen == 0) {
                /* Path like "/foo" -> parent is "/" */
                strcpy(parent, "/");
            } else {
                memcpy(parent, path, plen);
                parent[plen] = '\0';
            }
        } else {
            strcpy(parent, ".");
        }

        struct stat sb;
        if (stat(parent, &sb) != 0) {
            report_error(orig_path, strerror(errno));
            any_failure = 1;
            continue;
        }
        if (!S_ISDIR(sb.st_mode)) {
            report_error(orig_path, "Not a directory");
            any_failure = 1;
            continue;
        }

        /* Check if final component already exists (using stripped path) */
        struct stat dummy;
        if (stat(path, &dummy) == 0) {
            report_error(orig_path, "File exists");
            any_failure = 1;
            continue;
        } else if (errno != ENOENT) {
            /* Some other error accessing the path. */
            report_error(orig_path, strerror(errno));
            any_failure = 1;
            continue;
        }

        /* Attempt to create directory with default mode (0777 masked by umask). */
        if (mkdir(path, 0777) != 0) {
            report_error(orig_path, strerror(errno));
            any_failure = 1;
            continue;
        }
    }

    return any_failure ? 1 : 0;
}
