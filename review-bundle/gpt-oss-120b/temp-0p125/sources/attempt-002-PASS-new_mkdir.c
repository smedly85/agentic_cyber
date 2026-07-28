#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/stat.h>

static const char *progname = "mkdir";

int main(int argc, char *argv[]) {
    int any_failure = 0;
    int seen_double_dash = 0;
    int operand_count = 0;
    const char **operands = NULL;

    // First pass: count operands and detect unknown options
    for (int i = 1; i < argc; ++i) {
        const char *arg = argv[i];
        if (!seen_double_dash) {
            if (strcmp(arg, "--") == 0) { /* end of options */
                seen_double_dash = 1;
                continue;
            }
            if (arg[0] == '-' && strcmp(arg, "-") != 0) {
                fprintf(stderr, "%s: unrecognized option '%s'\nTry '%s --help' for more information.\n", progname, arg, progname);
                return 1; // immediate failure before any creation attempts
            }
        }
        ++operand_count; // treat as operand
    }

    if (operand_count == 0) {
        fprintf(stderr, "%s: missing operand\nTry '%s --help' for more information.\n", progname, progname);
        return 1;
    }

    operands = malloc(sizeof(char *) * operand_count);
    if (!operands) {
        perror("malloc");
        return 1;
    }

    // Second pass: collect operand strings
    int idx = 0;
    seen_double_dash = 0;
    for (int i = 1; i < argc; ++i) {
        const char *arg = argv[i];
        if (!seen_double_dash) {
            if (strcmp(arg, "--") == 0) { seen_double_dash = 1; continue; }
        }
        operands[idx++] = arg;
    }

    // Attempt to create each directory
    for (int i = 0; i < operand_count; ++i) {
        const char *path = operands[i];
        if (mkdir(path, 0777) != 0) {
            fprintf(stderr, "%s: cannot create directory '%s': %s\n", progname, path, strerror(errno));
            any_failure = 1;
        }
    }

    free((void *)operands);
    return any_failure ? 1 : 0;
}
