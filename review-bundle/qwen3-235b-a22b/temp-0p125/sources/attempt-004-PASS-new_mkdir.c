#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <errno.h>

int main(int argc, char *argv[]) {
    int i = 1;
    int saw_dashdash = 0;

    while (i < argc && !saw_dashdash) {
        if (strcmp(argv[i], "--") == 0) {
            i++;
            break;
        }
        if (argv[i][0] == '-' && argv[i][1] != '\0' && strcmp(argv[i], "-") != 0) {
            fprintf(stderr, "mkdir: unrecognized option '%s'\nTry 'mkdir --help' for more information.\n", argv[i]);
            return 1;
        }
        break;
    }

    if (argc - i == 0) {
        fprintf(stderr, "mkdir: missing operand\nTry 'mkdir --help' for more information.\n");
        return 1;
    }

    int success = 1;
    for (int j = 0; j < argc - i; j++) {
        if (mkdir(argv[i + j], 0777) != 0) {
            success = 0;
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n",
                    argv[i + j], strerror(errno));
        }
    }

    return success ? 0 : 1;
}