#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>

int main(int argc, char *argv[]) {
    int n_operands = 0;
    int after_ddash = 0;
    int i;

    if (argc < 2) {
        fprintf(stderr, "mkdir: missing operand\n"
                        "Try 'mkdir --help' for more information.\n");
        return 1;
    }

    for (i = 1; i < argc; i++) {
        const char *arg = argv[i];
        if (after_ddash == 0 && strcmp(arg, "--") == 0) {
            after_ddash = 1;
            continue;
        }
        if (after_ddash == 0 && arg[0] == '-' && arg[1] != '\0') {
            if (arg[1] == '-') {
                fprintf(stderr, "mkdir: unrecognized option '%s'\n"
                                "Try 'mkdir --help' for more information.\n",
                        arg);
            } else {
                fprintf(stderr, "mkdir: invalid option -- '%c'\n"
                                "Try 'mkdir --help' for more information.\n",
                        arg[1]);
            }
            return 1;
        }
        n_operands++;
    }

    if (n_operands == 0) {
        fprintf(stderr, "mkdir: missing operand\n"
                        "Try 'mkdir --help' for more information.\n");
        return 1;
    }

    after_ddash = 0;
    int all_ok = 1;

    for (i = 1; i < argc; i++) {
        const char *arg = argv[i];
        if (after_ddash == 0 && strcmp(arg, "--") == 0) {
            after_ddash = 1;
            continue;
        }
        errno = 0;
        if (mkdir(arg, 0777) == -1) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", arg, strerror(errno));
            all_ok = 0;
        }
    }

    return all_ok ? 0 : 1;
}
