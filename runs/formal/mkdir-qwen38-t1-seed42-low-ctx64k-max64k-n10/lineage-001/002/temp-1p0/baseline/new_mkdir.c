#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <errno.h>
#include <unistd.h>

static int create_parents = 0;

static int parse_args(int argc, char *argv[], int *first_operand_idx) {
    int i = 1;
    while (i < argc) {
        if (strcmp(argv[i], "--") == 0) {
            i++;
            break;
        }
        if (argv[i][0] == '-' && argv[i][1] != '\0') {
            if (strcmp(argv[i], "-p") == 0 || strcmp(argv[i], "--parents") == 0) {
                create_parents = 1;
                i++;
                continue;
            }
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

    *first_operand_idx = i;
    return 0;
}

static int make_parent_dirs(const char *path) {
    char *tmp = strdup(path);
    if (!tmp) return -1;

    char *p = tmp;
    if (*p == '/') p++;

    while (*p) {
        while (*p && *p != '/') p++;
        if (*p == '/') {
            *p = '\0';
            if (mkdir(tmp, 0777) != 0 && errno != EEXIST) {
                free(tmp);
                return -1;
            }
            *p = '/';
        }
        p++;
    }

    free(tmp);
    return 0;
}

int main(int argc, char *argv[]) {
    int first_operand;
    if (parse_args(argc, argv, &first_operand) != 0) {
        return 1;
    }

    int any_failed = 0;
    for (int j = first_operand; j < argc; j++) {
        const char *path = argv[j];

        if (create_parents) {
            if (make_parent_dirs(path) != 0) {
                fprintf(stderr, "mkdir: cannot create directory '%s': %s\n",
                        path, strerror(errno));
                any_failed = 1;
                continue;
            }
        }

        if (mkdir(path, 0777) != 0) {
            if (errno == EEXIST && create_parents) {
                // With -p, existing directory is not an error
                continue;
            }
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n",
                    path, strerror(errno));
            any_failed = 1;
        }
    }

    return any_failed ? 1 : 0;
}
