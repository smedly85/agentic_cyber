#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <errno.h>
#include <libgen.h>

int main(int argc, char *argv[]) {
    int optind = 1;
    int i;

    while (optind < argc) {
        if (strcmp(argv[optind], "--") == 0) {
            optind++;
            break;
        }
        if (argv[optind][0] == '-' && strcmp(argv[optind], "-") != 0) {
            fprintf(stderr, "mkdir: unrecognized option '%s'\nTry 'mkdir --help' for more information.\n", argv[optind]);
            return 1;
        }
        break;
    }

    if (optind < argc && strcmp(argv[optind], "--") == 0) {
        optind++;
    }

    if (optind >= argc) {
        fprintf(stderr, "mkdir: missing operand\nTry 'mkdir --help' for more information.\n");
        return 1;
    }

    int failure_count = 0;
    for (i = optind; i < argc; i++) {
        const char *path = argv[i];
        char *path_dup1 = strdup(path);
        char *path_dup2 = strdup(path);

        if (!path_dup1 || !path_dup2) {
            fprintf(stderr, "mkdir: memory allocation failed\n");
            free(path_dup1);
            free(path_dup2);
            failure_count++;
            continue;
        }

        char *parent = dirname(path_dup1);
        struct stat st;
        int error = 0;

        if (stat(parent, &st) != 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
            error = 1;
        } else if (!S_ISDIR(st.st_mode)) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(ENOTDIR));
            error = 1;
        }

        if (!error && stat(path, &st) == 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(EEXIST));
            error = 1;
        } else if (!error && errno != ENOENT) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
            error = 1;
        }

        if (!error && mkdir(path, 0777) != 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
            error = 1;
        }

        free(path_dup1);
        free(path_dup2);

        if (error) {
            failure_count++;
        }
    }

    return failure_count > 0 ? 1 : 0;
}