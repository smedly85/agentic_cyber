#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <errno.h>

int process_operand(char *path) {
    char *path_copy = strdup(path);
    char *end = path_copy + strlen(path_copy) - 1;
    while (end > path_copy && *end == '/') {
        *end-- = '\0';
    }
    if (!path_copy) {
        fprintf(stderr, "mkdir: memory allocation failed\n");
        return 1;
    }

    char *parent = path_copy;
    char *base = strrchr(parent, '/');
    if (base) {
        *base = '\0';
        base++;
        if (strlen(parent) == 0) parent = "/";
    } else {
        base = path_copy;
        parent = ".";
    }

    struct stat st;
    if (stat(parent, &st) != 0) {
        fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
        free(path_copy);
        return 1;
    }
    if (!S_ISDIR(st.st_mode)) {
        fprintf(stderr, "mkdir: cannot create directory '%s': Not a directory\n", path);
        free(path_copy);
        return 1;
    }

    if (lstat(path, &st) == 0) {
        fprintf(stderr, "mkdir: cannot create directory '%s': File exists\n", path);
        free(path_copy);
        return 1;
    } else if (errno != ENOENT) {
        fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
        free(path_copy);
        return 1;
    }

    if (mkdir(path, 0777) != 0) {
        fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
        free(path_copy);
        return 1;
    }

    free(path_copy);
    return 0;
}

int main(int argc, char *argv[]) {
    int opt_index = 1;
    while (opt_index < argc) {
        if (argv[opt_index][0] != '-') break;
        if (argv[opt_index][1] == '\0') break;
        if (strcmp(argv[opt_index], "--") == 0) {
            opt_index++;
            break;
        }
        fprintf(stderr, "mkdir: unrecognized option '%s'\nTry 'mkdir --help' for more information.\n", argv[opt_index]);
        return 1;
    }

    if (opt_index >= argc) {
        fprintf(stderr, "mkdir: missing operand\nTry 'mkdir --help' for more information.\n");
        return 1;
    }

    int failures = 0;
    for (int i = opt_index; i < argc; i++) {
        failures += process_operand(argv[i]);
    }
    return failures ? 1 : 0;
}