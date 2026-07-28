#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <errno.h>

int main(int argc, char *argv[]) {
    int i;
    int operands_start = 1;

    for (i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--") == 0) break;
        if (argv[i][0] == '-' && strcmp(argv[i], "-") != 0) {
            fprintf(stderr, "mkdir: unrecognized option '%s'\nTry 'mkdir --help' for more information.\n", argv[i]);
            return 1;
        }
    }

    if (i < argc && strcmp(argv[i], "--") == 0) operands_start = i + 1;
    if (operands_start >= argc) {
        fprintf(stderr, "mkdir: missing operand
Try 'mkdir --help' for more information.
\n");
        return 1;
    }

    int any_failed = 0;
    for (i = operands_start; i < argc; i++) {
        char *original_path = argv[i];
        size_t len = strlen(original_path);
        while (len > 1 && original_path[len-1] == '/') {
            len--;
        }
        char *path = strndup(original_path, len);
        if (!path) {
            fprintf(stderr, "mkdir: memory allocation failed\n");
            any_failed = 1;
            continue;
        }
        char *last_slash = strrchr(path, '/');
        char *parent;
        char *base;
        char *parent_dup = NULL;

        if (last_slash != NULL) {
            if (last_slash == path) {
                parent = "/";
                base = path + 1;
            } else {
                parent_dup = strndup(path, last_slash - path);
                if (!parent_dup) {
                    fprintf(stderr, "mkdir: memory allocation failed\n");
                    any_failed = 1;
                    continue;
                }
                parent = parent_dup;
                base = last_slash + 1;
            }
        } else {
            parent = ".";
            base = path;
        }

        struct stat sb;
        if (stat(parent, &sb) != 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s
\n", path, strerror(errno));
            any_failed = 1;
            free(path);
            free(parent_dup);
            continue;
        }
        if (!S_ISDIR(sb.st_mode)) {
            errno = ENOTDIR;
            fprintf(stderr, "mkdir: cannot create directory '%s': %s
\n", path, strerror(errno));
            any_failed = 1;
            free(path);
            free(parent_dup);
            continue;
        }

        char full_path[1024];
        snprintf(full_path, sizeof(full_path), "%s/%s", parent, base);
        if (stat(full_path, &sb) == 0) {
            errno = EEXIST;
            fprintf(stderr, "mkdir: cannot create directory '%s': %s
\n", path, strerror(errno));
            any_failed = 1;
            free(path);
            free(parent_dup);
            continue;
        }

        if (mkdir(full_path, 0777) != 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s
\n", path, strerror(errno));
            any_failed = 1;
        }
        free(parent_dup);
    }
    return any_failed ? 1 : 0;
}