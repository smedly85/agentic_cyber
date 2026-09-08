#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>

int main(int argc, char *argv[])
{
    int i;
    int options_done = 0;

    /* First pass: detect unknown options (immediate failure). */
    for (i = 1; i < argc; i++) {
        if (options_done)
            continue;
        if (strcmp(argv[i], "--") == 0) {
            options_done = 1;
        } else if (argv[i][0] == '-' && argv[i][1] != '\0') {
            fprintf(stderr, "mkdir: unrecognized option '%s'\nTry 'mkdir --help' for more information.\n", argv[i]);
            return 1;
        }
    }

    /* Count operands. */
    options_done = 0;
    int operands = 0;
    for (i = 1; i < argc; i++) {
        if (!options_done && strcmp(argv[i], "--") == 0) {
            options_done = 1;
            continue;
        }
        operands++;
    }

    if (operands == 0) {
        fprintf(stderr, "mkdir: missing operand\nTry 'mkdir --help' for more information.\n");
        return 1;
    }

    /* Create each directory; continue after per-operand failure. */
    options_done = 0;
    int failed = 0;
    for (i = 1; i < argc; i++) {
        if (!options_done && strcmp(argv[i], "--") == 0) {
            options_done = 1;
            continue;
        }
        if (mkdir(argv[i], 0777) != 0) {
            int err = errno;
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n",
                    argv[i], strerror(err));
            failed = 1;
        }
    }

    return failed ? 1 : 0;
}
