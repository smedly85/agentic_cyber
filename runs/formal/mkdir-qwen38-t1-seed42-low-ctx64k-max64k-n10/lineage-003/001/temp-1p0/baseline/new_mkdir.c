#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <errno.h>
#include <unistd.h>

int main(int argc, char *argv[]) {
    int i;
    int end_of_options = 0;
    int has_operand = 0;
    int ret = 0;

    for (i = 1; i < argc; i++) {
        const char *arg = argv[i];
        if (strcmp(arg, "--") == 0) {
            end_of_options = 1;
            continue;
        }
        if (!end_of_options && arg[0] == '-' && arg[1] != '\0') {
            fprintf(stderr, "mkdir: unrecognized option '%s'\n", arg);
            fprintf(stderr, "Try 'mkdir --help' for more information.\n");
            return 1;
        }
        has_operand = 1;
    }

    if (!has_operand) {
        fprintf(stderr, "mkdir: missing operand\n");
        fprintf(stderr, "Try 'mkdir --help' for more information.\n");
        return 1;
    }

    for (i = 1; i < argc; i++) {
        const char *arg = argv[i];
        if (strcmp(arg, "--") == 0) continue;
        if (mkdir(arg, 0777) != 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n",
                    arg, strerror(errno));
            ret = 1;
        }
    }

    return ret;
}
