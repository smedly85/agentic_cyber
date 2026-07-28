#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/stat.h>
#include <unistd.h>
#include <libgen.h>

int main(int argc, char *argv[]) {
    for (int i = 1; i < argc; i++) {
        if (argv[i][0] == '-') {
            if (strcmp(argv[i], "--") == 0) break;
            else if (strlen(argv[i]) == 1) continue;
            else {
                fprintf(stderr, "mkdir: unrecognized option '%s'\nTry 'mkdir --help' for more information.\n", argv[i]);
                return 1;
            }
        }
    }

    int operands_start = 1;
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--") == 0) {
            operands_start = i + 1;
            break;
        }
    }
    if (operands_start >= argc) {
        fprintf(stderr, "mkdir: missing operand\nTry 'mkdir --help' for more information.\n");
        return 1;
    }

    int failures = 0;
    for (int i = operands_start; i < argc; i++) {
        char *path = argv[i];
        char *path_dup = strdup(path);
        if (!path_dup) {
            fprintf(stderr, "mkdir: memory allocation failed\n");
            return 1;
        }
        char *parent = dirname(path_dup);

        struct stat sb;
        if (stat(parent, &sb) != 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
            failures++;
            free(path_dup);
            continue;
        }
        if (!S_ISDIR(sb.st_mode)) {
            fprintf(stderr, "mkdir: cannot create directory '%s': Not a directory\n", path);
            failures++;
            free(path_dup);
            continue;
        }
        if (stat(path, &sb) == 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': File exists\n", path);
            failures++;
            free(path_dup);
            continue;
        } else if (errno != ENOENT) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
            failures++;
            free(path_dup);
            continue;
        }
        if (mkdir(path, 0777) != 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
            failures++;
        }
        free(path_dup);
    }
    return failures ? 1 : 0;
}