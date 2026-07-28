#include <stdio.h>
#include <stdlib.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <errno.h>
#include <string.h>

#define MAX_OPERANDS 1000

int main(int argc, char *argv[]) {
    int i = 1;
    int after_dd = 0;

    while (i < argc) {
        if (strcmp(argv[i], "--") == 0) {
            after_dd = 1;
            i++;
            break;
        }
        if (argv[i][0] == '-' && strcmp(argv[i], "-") != 0) {
            fprintf(stderr, "mkdir: unrecognized option '%s'\nTry 'mkdir --help' for more information.\n", argv[i]);
            return 1;
        }
        i++;
    }

    char *operands[MAX_OPERANDS];
    int op_count = 0;

    while (i < argc) {
        operands[op_count++] = argv[i++];
    }

    if (!after_dd) {
        for (int j = 1; j < i; j++) {
            if (argv[j][0] != '-' || strcmp(argv[j], "-") == 0) {
                operands[op_count++] = argv[j];
            }
        }
    }

    if (op_count == 0) {
        fprintf(stderr, "mkdir: missing operand\nTry 'mkdir --help' for more information.\n");
        return 1;
    }

    int any_failed = 0;
    for (i = 0; i < op_count; i++) {
        if (mkdir(operands[i], 0777) == -1) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n",
                    operands[i], strerror(errno));
            any_failed = 1;
        }
    }

    return any_failed ? 1 : 0;
}