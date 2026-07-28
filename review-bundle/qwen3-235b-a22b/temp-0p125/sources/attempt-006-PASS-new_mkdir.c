#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <libgen.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>
#include <errno.h>

int main(int argc, char *argv[]) {
    int start = 1;
    int failed = 0;

    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--") == 0) {
            start = i + 1;
            break;
        } else if (argv[i][0] == '-' && argv[i][1] != '\0') {
            fprintf(stderr, "mkdir: unrecognized option '%s'\nTry 'mkdir --help' for more information.\n", argv[i]);
            exit(1);
        }
    }

    if (start >= argc) {
        fprintf(stderr, "mkdir: missing operand\nTry 'mkdir --help' for more information.\n");
        exit(1);
    }

    for (int i = start; i < argc; i++) {
        char *operand = argv[i];
        if (*operand == '\0') {
            fprintf(stderr, "mkdir: cannot create directory '%s': Invalid path\n", operand);
            failed = 1;
            continue;
        }

        char *path_copy1 = strdup(operand);
        if (!path_copy1) {
            perror("new_mkdir");
            exit(1);
        }
        char *parent_path = dirname(path_copy1);

        struct stat st;

        if (stat(parent_path, &st) != 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", operand, strerror(errno));
            free(path_copy1);

            failed = 1;
            continue;
        }

        if (!S_ISDIR(st.st_mode)) {
            fprintf(stderr, "mkdir: cannot create directory '%s': Not a directory\n", operand);
            free(path_copy1);

            failed = 1;
            continue;
        }

        if (stat(operand, &st) == 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': File exists\n", operand);
            free(path_copy1);

            failed = 1;
            continue;
        }

        if (mkdir(operand, 0777) != 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", operand, strerror(errno));
            free(path_copy1);

            failed = 1;
            continue;
        }

        free(path_copy1);

    }

    return failed ? 1 : 0;
}