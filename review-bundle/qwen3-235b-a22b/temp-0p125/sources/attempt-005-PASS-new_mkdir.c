#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <libgen.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>
#include <errno.h>

int main(int argc, char **argv) {
    char **operands = NULL;
    int operand_count = 0;
    int i = 1;

    while (i < argc) {
        if (strcmp(argv[i], "--") == 0) {
            i++;
            break;
        } else if (argv[i][0] == '-') {
            if (strcmp(argv[i], "-") == 0) {
                operands = realloc(operands, (operand_count + 1) * sizeof(char *));
                operands[operand_count++] = "-";
            } else {
                fprintf(stderr, "mkdir: unrecognized option '%s'\nTry 'mkdir --help' for more information.\n", argv[i]);
                return 1;
            }
        } else {
            operands = realloc(operands, (operand_count + 1) * sizeof(char *));
            operands[operand_count++] = argv[i];
        }
        i++;
    }

    while (i < argc) {
        operands = realloc(operands, (operand_count + 1) * sizeof(char *));
        operands[operand_count++] = argv[i++];
    }

    if (operand_count == 0) {
        fprintf(stderr, "mkdir: missing operand\nTry 'mkdir --help' for more information.\n");
        return 1;
    }

    int failures = 0;
    for (int j = 0; j < operand_count; j++) {
        char *path = operands[j];
        char *path_dup = strdup(path);
        if (!path_dup) {
            perror("new_mkdir");
            failures++;
            continue;
        }
        char *parent = dirname(path_dup);

        struct stat st;
        if (stat(parent, &st) != 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
            failures++;
            free(path_dup);
            continue;
        }
        if (!S_ISDIR(st.st_mode)) {
            fprintf(stderr, "mkdir: cannot create directory '%s': Not a directory\n", path);
            failures++;
            free(path_dup);
            continue;
        }
        if (stat(path, &st) == 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': File exists\n", path);
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

    free(operands);
    return failures ? 1 : 0;
}
