#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <errno.h>
#include <limits.h>

int main(int argc, char *argv[]) {
    if (argc < 2) {
        fprintf(stderr, "mkdir: missing operand\nTry 'mkdir --help' for more information.\n");
        return 1;
    }

    int end_of_options = 0;
    // First pass: collect operands and check for unknown options.
    char **operands = malloc(sizeof(char *) * argc);
    if (!operands) {
        fprintf(stderr, "new_mkdir: memory allocation failure\n");
        return 1;
    }
    int opcnt = 0;

    for (int i = 1; i < argc; ++i) {
        char *arg = argv[i];
        if (!end_of_options && strcmp(arg, "--") == 0) {
            end_of_options = 1;
            continue;
        }
        // Option detection (excluding single dash and after '--')
        if (!end_of_options && arg[0] == '-' && strcmp(arg, "-") != 0) {
            fprintf(stderr, "mkdir: unrecognized option '%s'\nTry 'mkdir --help' for more information.\n", arg);
            free(operands);
            return 1;
        }
        // Treat as operand
        operands[opcnt++] = arg;
    }

    if (opcnt == 0) {
        fprintf(stderr, "new_mkdir: missing operand\n");
        free(operands);
        return 1;
    }

    int overall_status = 0; // 0 = all succeeded, 1 = at least one failed

    for (int i = 0; i < opcnt; ++i) {
        const char *orig_path = operands[i];
        /* Strip trailing slashes (except when the whole path is just "/") */
        size_t orig_len = strlen(orig_path);
        while (orig_len > 1 && orig_path[orig_len - 1] == '/') {
            orig_len--;
        }
        char path[PATH_MAX];
        memcpy(path, orig_path, orig_len);
        path[orig_len] = '\0';

        /* Determine parent directory based on normalized path */
        const char *slash = strrchr(path, '/');
        char parent_buf[PATH_MAX];
        if (slash) {
            size_t plen = slash - path;
            if (plen == 0) {
                /* Path like "/foo" -> parent is "/" */
                strcpy(parent_buf, "/");
            } else {
                memcpy(parent_buf, path, plen);
                parent_buf[plen] = '\0';
            }
        } else {
            /* No slash => parent is current directory "." */
            strcpy(parent_buf, ".");
        }

        struct stat st;
        // Check parent existence and that it is a directory.
        if (stat(parent_buf, &st) != 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
            overall_status = 1;
            continue;
        }
        if (!S_ISDIR(st.st_mode)) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(ENOTDIR));
            overall_status = 1;
            continue;
        }
        // Check whether final component already exists.
        if (stat(path, &st) == 0) {
            /* Exists */
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(EEXIST));
            overall_status = 1;
            continue;
        }
        // Attempt to create directory.
        if (mkdir(path, 0777) != 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
            overall_status = 1;
            continue;
        }
    }

    free(operands);
    return overall_status;
}
