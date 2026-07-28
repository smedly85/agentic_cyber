#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/stat.h>
#include <limits.h>
#include <unistd.h>

static void print_error(const char *path, const char *msg) {
    fprintf(stderr, "new_mkdir: cannot create directory '%s': %s\n", path, msg);
}

int main(int argc, char *argv[]) {
    int after_dashdash = 0;
    int operand_count = 0;
    // First pass to validate options and count operands
    for (int i = 1; i < argc; ++i) {
        const char *arg = argv[i];
        if (!after_dashdash && strcmp(arg, "--") == 0) {
            after_dashdash = 1;
            continue;
        }
        if (!after_dashdash && arg[0] == '-' && !(strcmp(arg, "-") == 0)) {
            // Unknown option
            fprintf(stderr, "new_mkdir: unrecognized option '%s'\n", arg);
            return 1;
        }
        // Operand (including a single dash)
        operand_count++;
    }

    if (operand_count == 0) {
        fprintf(stderr, "new_mkdir: missing operand\n");
        return 1;
    }

    int any_failure = 0;
    after_dashdash = 0; // reset for second pass
    for (int i = 1; i < argc; ++i) {
        const char *arg = argv[i];
        if (!after_dashdash && strcmp(arg, "--") == 0) {
            after_dashdash = 1;
            continue;
        }
        if (!after_dashdash && arg[0] == '-' && !(strcmp(arg, "-") == 0)) {
            // already handled
            continue;
        }
        const char *path = arg;
        /* Determine parent directory */
        const char *slash = strrchr(path, '/');
        char parent[PATH_MAX];
        if (slash) {
            size_t len = slash - path; // length before last slash
            if (len == 0) {
                // Path like "/foo" where parent is root ""
                strcpy(parent, "/");
            } else {
                memcpy(parent, path, len);
                parent[len] = '\0';
            }
        } else {
            strcpy(parent, ".");
        }

        struct stat sb;
        if (stat(parent, &sb) != 0) {
            print_error(path, strerror(errno));
            any_failure = 1;
            continue;
        }
        if (!S_ISDIR(sb.st_mode)) {
            print_error(path, "Not a directory");
            any_failure = 1;
            continue;
        }

        // Check if final component already exists
        struct stat sb2;
        if (stat(path, &sb2) == 0) {
            print_error(path, "File exists");
            any_failure = 1;
            continue;
        } else if (errno != ENOENT) {
            // Some other error attempting to stat the target
            print_error(path, strerror(errno));
            any_failure = 1;
            continue;
        }

        if (mkdir(path, 0777) != 0) {
            print_error(path, strerror(errno));
            any_failure = 1;
            continue;
        }
    }

    return any_failure ? 1 : 0;
}
