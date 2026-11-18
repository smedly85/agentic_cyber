#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>

#define PROGNAM "mkdir"

int main(int argc, char *argv[])
{
    int in_positional = 0;
    int operand_count = 0;
    int any_failed = 0;
    int i;

    /* Phase 1: validate — scan all arguments before any filesystem mutation. */
    for (i = 1; i < argc; i++) {
        const char *arg = argv[i];
        if (in_positional) {
            operand_count++;
        } else if (strcmp(arg, "--") == 0) {
            in_positional = 1;
        } else if (arg[0] == '-' && arg[1] != '\0') {
            if (arg[1] == '-')
                fprintf(stderr, "%s: unrecognized option '%s'\n",
                        PROGNAM, arg);
            else
                fprintf(stderr, "%s: invalid option -- '%c'\n",
                        PROGNAM, arg[1]);
            fprintf(stderr, "Try '%s --help' for more information.\n", PROGNAM);
            return 1;
        } else {
            operand_count++;
        }
    }

    if (operand_count == 0) {
        fprintf(stderr, "%s: missing operand\n", PROGNAM);
        fprintf(stderr, "Try '%s --help' for more information.\n", PROGNAM);
        return 1;
    }

    /* Phase 2: create each operand in order; continue after per-operand errors. */
    in_positional = 0;
    for (i = 1; i < argc; i++) {
        const char *arg = argv[i];
        if (in_positional) {
            if (mkdir(arg, 0777) != 0) {
                any_failed = 1;
                fprintf(stderr, "%s: cannot create directory '%s': %s\n",
                        PROGNAM, arg, strerror(errno));
            }
        } else if (strcmp(arg, "--") == 0) {
            in_positional = 1;
        } else if (arg[0] == '-' && arg[1] != '\0') {
            /* unreachable: phase 1 already rejected unknown options */
            continue;
        } else {
            if (mkdir(arg, 0777) != 0) {
                any_failed = 1;
                fprintf(stderr, "%s: cannot create directory '%s': %s\n",
                        PROGNAM, arg, strerror(errno));
            }
        }
    }

    return any_failed;
}
