#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <libgen.h>
#include <sys/stat.h>
#include <errno.h>
#include <limits.h>

int main(int argc, char *argv[]) {
    char *operands[argc];
    int num_operands = 0;
    int saw_dashdash = 0;
    int i;

    for (i = 1; i < argc; i++) {
        if (!saw_dashdash && argv[i][0] == '-') {
            if (strcmp(argv[i], "--") == 0) {
                saw_dashdash = 1;
            } else if (strlen(argv[i]) == 1) {
                operands[num_operands++] = argv[i];
            } else {
                fprintf(stderr, "mkdir: unrecognized option '%s'\nTry 'mkdir --help' for more information.\n", argv[i]);
                return 1;
            }
        } else {
            operands[num_operands++] = argv[i];
        }
    }

    if (num_operands == 0) {
        fprintf(stderr, "mkdir: missing operand\nTry 'mkdir --help' for more information.\n");
        return 1;
    }

    int failures = 0;
    for (i = 0; i < num_operands; i++) {
        char *path = operands[i];
        char *path_dup1 = strdup(path);
        char *path_dup2 = strdup(path);
        if (!path_dup1 || !path_dup2) {
            fprintf(stderr, "mkdir: out of memory\n");
            exit(1);
        }

        char *parent = dirname(path_dup1);
        char *name = basename(path_dup2);

        struct stat st;
        if (stat(parent, &st) != 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
            failures = 1;
            free(path_dup1);
            free(path_dup2);
            continue;
        }
        if (!S_ISDIR(st.st_mode)) {
            fprintf(stderr, "mkdir: cannot create directory '%s': Not a directory\n", path);
            failures = 1;
            free(path_dup1);
            free(path_dup2);
            continue;
        }

        char full_path[PATH_MAX];
        snprintf(full_path, PATH_MAX, "%s/%s", parent, name);
        struct stat st2;
        if (stat(full_path, &st2) == 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': File exists\n", path);
            failures = 1;
            free(path_dup1);
            free(path_dup2);
            continue;
        }

        if (mkdir(full_path, 0777) == -1) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
            failures = 1;
        }

        free(path_dup1);
        free(path_dup2);
    }

    return failures ? 1 : 0;
}