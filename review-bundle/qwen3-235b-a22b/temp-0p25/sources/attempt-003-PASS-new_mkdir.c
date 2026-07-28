#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <libgen.h>
#include <sys/stat.h>
#include <errno.h>
#include <stdbool.h>

int main(int argc, char *argv[]) {
    char **operands = NULL;
    int operands_count = 0;
    int end_of_options = 0;

    for (int i = 1; i < argc; i++) {
        if (!end_of_options && strcmp(argv[i], "--") == 0) {
            end_of_options = 1;
            continue;
        } else if (!end_of_options && argv[i][0] == '-' && argv[i][1] != '\0') {
            if (strcmp(argv[i], "-") != 0) {
                fprintf(stderr, "mkdir: unrecognized option '%s'\nTry 'mkdir --help' for more information.\n", argv[i]);
                exit(1);
            }
        }
        operands = realloc(operands, (operands_count + 1) * sizeof(char*));
        if (!operands) {
            fprintf(stderr, "new_mkdir: memory allocation failed\n");
            exit(1);
        }
        operands[operands_count++] = argv[i];
    }

    if (operands_count == 0) {
        fprintf(stderr, "mkdir: missing operand\nTry 'mkdir --help' for more information.\n");
        exit(1);
    }

    bool any_failure = false;

    for (int i = 0; i < operands_count; i++) {
        char *operand = operands[i];
        char *path_copy = strdup(operand);
        char *dir_copy = strdup(operand);
        if (!path_copy || !dir_copy) {
            fprintf(stderr, "new_mkdir: memory allocation failed\n");
            exit(1);
        }
        char *parent_path = dirname(dir_copy);
        char *base_name = basename(path_copy);

        if (base_name[0] == '\0') {
            fprintf(stderr, "mkdir: cannot create directory '%s': Invalid directory name\n", operand);
            any_failure = true;
            free(path_copy);
            free(dir_copy);
            continue;
        }

        struct stat sb;
        if (stat(parent_path, &sb) == -1) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", operand, strerror(errno));
            any_failure = true;
            free(path_copy);
            free(dir_copy);
            continue;
        }
        if (!S_ISDIR(sb.st_mode)) {
            fprintf(stderr, "mkdir: cannot create directory '%s': Not a directory\n", operand);
            any_failure = true;
            free(path_copy);
            free(dir_copy);
            continue;
        }

        char *full_path;
        if (asprintf(&full_path, "%s/%s", parent_path, base_name) == -1) {
            fprintf(stderr, "new_mkdir: memory allocation failed\n");
            exit(1);
        }

        if (stat(full_path, &sb) != -1) {
            fprintf(stderr, "mkdir: cannot create directory '%s': File exists\n", operand);
            any_failure = true;
        } else if (errno != ENOENT) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", operand, strerror(errno));
            any_failure = true;
        } else {
            if (mkdir(full_path, 0777) == -1) {
                fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", operand, strerror(errno));
                any_failure = true;
            }
        }

        free(full_path);
        free(path_copy);
        free(dir_copy);
    }

    free(operands);
    exit(any_failure ? 1 : 0);
}