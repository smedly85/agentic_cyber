#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <libgen.h>
#include <sys/stat.h>
#include <unistd.h>
#include <errno.h>

int main(int argc, char *argv[]) {
    int optind = 1;

// Parse options
while (optind < argc && argv[optind][0] == '-') {
    if (strcmp(argv[optind], "--") == 0) {
        optind++;
        break;
    }
    if (strcmp(argv[optind], "-") == 0) {
        break;
    }
    fprintf(stderr, "mkdir: unrecognized option '%s'\nTry 'mkdir --help' for more information.\n", argv[optind]);
    return 1;
}

    // Handled in options parsing

    if (optind >= argc) {
        fprintf(stderr, "mkdir: missing operand\nTry 'mkdir --help' for more information.\n");
        return 1;
    }

    int failures = 0;
    for (int i = optind; i < argc; i++) {
    char *path = argv[i];
    char *path_copy = strdup(path);
    // Strip trailing slashes
    size_t len = strlen(path_copy);
    while (len > 0 && path_copy[len-1] == '/') {
        len--;
    }
    path_copy[len] = '\0';
    if (!path_copy) {
            fprintf(stderr, "new_mkdir: memory allocation error\n");
            return 1;
        }

        char *dir = dirname(path_copy);
        struct stat st;

        if (stat(dir, &st) == -1) {
            if (errno == ENOENT) {
                fprintf(stderr, "mkdir: cannot create directory '%s': No such file or directory\n", path);
            } else {
fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
            }
            failures++;
            free(path_copy);
            continue;
        }

        if (!S_ISDIR(st.st_mode)) {
            fprintf(stderr, "mkdir: cannot create directory '%s': Not a directory\n", path);
            failures++;
            free(path_copy);
            continue;
        }

        if (stat(path, &st) == 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': File exists\n", path);
            failures++;
            free(path_copy);
            continue;
        }

        if (mkdir(path, 0777) == -1) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
            failures++;
        }
        free(path_copy);
    }

    return failures ? 1 : 0;
}