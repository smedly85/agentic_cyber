#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <errno.h>

int main(int argc, char *argv[]) {
    /* Find the first operand. Before that, only '--' is recognized;
       any other '-'-prefixed argument is an unknown option. */
    int i = 1;
    while (i < argc) {
        if (strcmp(argv[i], "--") == 0) {
            i++;
            break;
        }
        if (argv[i][0] == '-' && argv[i][1] != '\0') {
            fprintf(stderr, "mkdir: unrecognized option '%s'\n"
                            "Try 'mkdir --help' for more information.\n",
                    argv[i]);
            return 1;
        }
        break;
    }

    if (i >= argc) {
        fprintf(stderr, "mkdir: missing operand\n"
                        "Try 'mkdir --help' for more information.\n");
        return 1;
    }

    int any_failed = 0;
    for (int j = i; j < argc; j++) {
        if (mkdir(argv[j], 0777) != 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n",
                    argv[j], strerror(errno));
            any_failed = 1;
        }
    }

    return any_failed ? 1 : 0;
}
