#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <limits.h>
#include <errno.h>

int main(int argc, char *argv[]) {
    int end_of_options = 0;
    int any_failure = 0;
    // Collect operand pointers; they simply point into argv, no allocation needed.
    const char **operands = NULL;
    size_t operands_cap = 0, operands_len = 0;

    for (int i = 1; i < argc; ++i) {
        const char *arg = argv[i];
        if (!end_of_options) {
            if (strcmp(arg, "--") == 0) {
                end_of_options = 1;
                continue;
            }
            if (arg[0] == '-' && !(arg[0] == '-' && arg[1] == '\0')) { // unknown option (not bare '-')
                fprintf(stderr, "new_mkdir: unrecognized option '%s'\n", arg);
                return 1;
            }
        }
        // treat as operand
        if (operands_len == operands_cap) {
            size_t newcap = operands_cap ? operands_cap * 2 : 4;
            const char **tmp = realloc(operands, newcap * sizeof(*tmp));
            if (!tmp) {
                fprintf(stderr, "new_mkdir: memory allocation failed\n");
                free(operands);
                return 1;
            }
            operands = tmp;
            operands_cap = newcap;
        }
        operands[operands_len++] = arg;
    }

    if (operands_len == 0) {
        fprintf(stderr, "new_mkdir: missing operand\n");
        free(operands);
        return 1;
    }

    for (size_t idx = 0; idx < operands_len; ++idx) {
        const char *path = operands[idx];
        // Determine parent directory.
        const char *slash = strrchr(path, '/');
        char parent[PATH_MAX];
        if (slash) {
            size_t plen = slash - path;
            if (plen == 0) {
                // Path like "/foo" => parent is "/"
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
            fprintf(stderr, "new_mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
            any_failure = 1;
            continue;
        }
        if (!S_ISDIR(sb.st_mode)) {
            fprintf(stderr, "new_mkdir: cannot create directory '%s': Not a directory\n", path);
            any_failure = 1;
            continue;
        }

        // Check final component existence.
        if (stat(path, &sb) == 0) {
            fprintf(stderr, "new_mkdir: cannot create directory '%s': File exists\n", path);
            any_failure = 1;
            continue;
        } else if (errno != ENOENT) {
            // Some other error while checking existence.
            fprintf(stderr, "new_mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
            any_failure = 1;
            continue;
        }

        // Attempt to create the directory with default mode (0777 masked by umask).
        if (mkdir(path, 0777) != 0) {
            fprintf(stderr, "new_mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
            any_failure = 1;
            continue;
        }
    }

    free(operands);
    return any_failure ? 1 : 0;
}
