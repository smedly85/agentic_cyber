#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <libgen.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

int main(int argc, char *argv[]) {
    int optind = 1;
    int error_occurred = 0;

    while (optind < argc && argv[optind][0] == '-') {
        if (argv[optind][1] == '\0') break;
        if (argv[optind][1] == '-' && argv[optind][2] == '\0') {
            optind++;
            break;
        }
         fprintf(stderr, "mkdir: unrecognized option '%s'\nTry 'mkdir --help' for more information.\n", argv[optind]);
        return 1;
    }

    if (optind >= argc) {
         fprintf(stderr, "mkdir: missing operand\nTry 'mkdir --help' for more information.\n");
        return 1;
    }

    for (int i = optind; i < argc; i++) {
        char *path = argv[i];
        char *dir_copy = strdup(path);
        if (!dir_copy) {
            fprintf(stderr, "mkdir: memory allocation failed\n");
            error_occurred = 1;
            free(dir_copy);
            continue;
        }

        char *parent = dirname(dir_copy);
        struct stat st;

        if (stat(parent, &st) != 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
            error_occurred = 1;
        } else if (!S_ISDIR(st.st_mode)) {
            fprintf(stderr, "mkdir: cannot create directory '%s': Not a directory\n", path);
            error_occurred = 1;
        } else if (stat(path, &st) == 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': File exists\n", path);
            error_occurred = 1;
        } else if (mkdir(path, 0777) != 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
            error_occurred = 1;
        }

        free(dir_copy);
    }

    return error_occurred ? 1 : 0;
}