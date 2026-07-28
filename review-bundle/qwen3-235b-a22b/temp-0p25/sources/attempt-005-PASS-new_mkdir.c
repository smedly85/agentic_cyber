#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <errno.h>
#include <libgen.h>

int process_operand(char *path) {
    char *dname_copy = strdup(path);
    if (!dname_copy) {
        fprintf(stderr, "mkdir: out of memory\n");
        return 0;
    }
    char *parent = dirname(dname_copy);

    char *bname_copy = strdup(path);
    if (!bname_copy) {
        free(dname_copy);
        fprintf(stderr, "mkdir: out of memory\n");
        return 0;
    }
    char *final = basename(bname_copy);

    struct stat st;
    if (stat(parent, &st) != 0) {
        fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
        free(dname_copy);
        free(bname_copy);
        return 0;
    }

    if (!S_ISDIR(st.st_mode)) {
        errno = ENOTDIR;
        fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
        free(dname_copy);
        free(bname_copy);
        return 0;
    }

    size_t len = strlen(parent) + strlen(final) + 2;
    char *full_path = malloc(len);
    if (!full_path) {
        free(dname_copy);
        free(bname_copy);
        fprintf(stderr, "mkdir: out of memory\n");
        return 0;
    }
    snprintf(full_path, len, "%s/%s", parent, final);

    if (stat(full_path, &st) == 0) {
        errno = EEXIST;
        fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
        free(full_path);
        free(dname_copy);
        free(bname_copy);
        return 0;
    }

    if (mkdir(full_path, 0777) != 0) {
        fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
        free(full_path);
        free(dname_copy);
        free(bname_copy);
        return 0;
    }

    free(full_path);
    free(dname_copy);
    free(bname_copy);
    return 1;
}

int main(int argc, char *argv[]) {
    int i = 1;
    while (i < argc) {
        if (strcmp(argv[i], "--") == 0) {
            i++;
            break;
        }
        if (argv[i][0] == '-' && strcmp(argv[i], "-") != 0) {
            fprintf(stderr, "mkdir: unrecognized option '%s'\nTry 'mkdir --help' for more information.\n", argv[i]);
            return 1;
        }
        break;
    }

    if (i >= argc) {
fprintf(stderr, "mkdir: missing operand\nTry 'mkdir --help' for more information.\n");
    return 1;
    }

    int success = 1;
    for (; i < argc; i++) {
        if (!process_operand(argv[i])) {
            success = 0;
        }
    }

    return success ? 0 : 1;
}