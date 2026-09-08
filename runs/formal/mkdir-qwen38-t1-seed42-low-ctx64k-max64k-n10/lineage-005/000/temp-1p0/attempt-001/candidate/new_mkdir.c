#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>

int main(int argc, char *argv[])
{
    int end_of_options = 0;
    int operand_count = 0;
    int operand_cap = 0;
    int any_failed = 0;
    int *operands = NULL;

    for (int i = 1; i < argc; i++) {
        if (!end_of_options) {
            if (strcmp(argv[i], "--") == 0) {
                end_of_options = 1;
                continue;
            }
            if (argv[i][0] == '-' && strcmp(argv[i], "-") != 0) {
                fprintf(stderr, "mkdir: unrecognized option '%s'\n", argv[i]);
                fprintf(stderr, "Try 'mkdir --help' for more information.\n");
                free(operands);
                return 1;
            }
        }
        if (operand_count == operand_cap) {
            int new_cap = operand_cap ? operand_cap * 2 : 8;
            int *tmp = realloc(operands, (size_t)new_cap * sizeof(int));
            if (!tmp) {
                fprintf(stderr, "mkdir: memory allocation failed\n");
                free(operands);
                return 1;
            }
            operands = tmp;
            operand_cap = new_cap;
        }
        operands[operand_count++] = i;
    }

    if (operand_count == 0) {
        fprintf(stderr, "mkdir: missing operand\n");
        fprintf(stderr, "Try 'mkdir --help' for more information.\n");
        free(operands);
        return 1;
    }

    for (int i = 0; i < operand_count; i++) {
        const char *path = argv[operands[i]];
        if (mkdir(path, 0777) != 0) {
            any_failed = 1;
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n",
                    path, strerror(errno));
        }
    }

    free(operands);
    return any_failed ? 1 : 0;
}
