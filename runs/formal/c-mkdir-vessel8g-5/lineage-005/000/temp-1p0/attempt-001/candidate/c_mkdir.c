#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/stat.h>
#include <sys/types.h>

int main(int argc, char *argv[])
{
    int *operands;
    int n_operands;
    int i, j;
    int end_of_options;
    int all_ok;

    operands = malloc((size_t)argc * sizeof(int));
    if (operands == NULL) {
        fprintf(stderr, "mkdir: memory allocation failed\n");
        return 1;
    }

    n_operands = 0;
    end_of_options = 0;

    for (i = 1; i < argc; i++) {
        if (!end_of_options) {
            if (strcmp(argv[i], "--") == 0) {
                end_of_options = 1;
                continue;
            }
            if (argv[i][0] == '-' && argv[i][1] != '\0') {
                fprintf(stderr, "mkdir: unrecognized option '%s'\n", argv[i]);
                fprintf(stderr, "Try 'mkdir --help' for more information.\n");
                free(operands);
                return 1;
            }
        }
        operands[n_operands++] = i;
    }

    if (n_operands == 0) {
        fprintf(stderr, "mkdir: missing operand\n");
        fprintf(stderr, "Try 'mkdir --help' for more information.\n");
        free(operands);
        return 1;
    }

    all_ok = 1;
    for (j = 0; j < n_operands; j++) {
        const char *path = argv[operands[j]];
        if (mkdir(path, 0777) != 0) {
            int err = errno;
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n",
                    path, strerror(err));
            all_ok = 0;
        }
    }

    free(operands);
    return all_ok ? 0 : 1;
}
