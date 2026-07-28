#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/stat.h>
#include <unistd.h>
#include <limits.h>

static void print_error(const char *path) {
    fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        fprintf(stderr, "missing operand\n");
        return 1;
    }
    int any_failure = 0;
    int i = 1;
    // handle '--'
    for (; i < argc; ++i) {
        if (strcmp(argv[i], "--") == 0) { i++; break; }
        if (argv[i][0] == '-' && strcmp(argv[i], "-") != 0) {
            fprintf(stderr, "unrecognized option %s\n", argv[i]);
            return 1;
        }
    }
    // after '--' or first non-option arguments
    if (i >= argc) {
        fprintf(stderr, "missing operand\n");
        return 1;
    }
    for (; i < argc; ++i) {
        const char *path = argv[i];
        // find parent directory
        const char *slash = strrchr(path, '/');
        char parent[PATH_MAX];
        if (slash) {
            size_t len = slash - path;
            if (len == 0) { // leading slash -> root
                strcpy(parent, "/");
            } else {
                strncpy(parent, path, len);
                parent[len] = '\0';
            }
        } else {
            strcpy(parent, ".");
        }
        struct stat st;
        if (stat(parent, &st) != 0) {
            // parent does not exist or cannot be accessed
            print_error(path);
            any_failure = 1;
            continue;
        }
        if (!S_ISDIR(st.st_mode)) {
            print_error(path);
            any_failure = 1;
            continue;
        }
        // check if target already exists
        if (stat(path, &st) == 0) {
            errno = EEXIST; // ensure message matches existing case
            print_error(path);
            any_failure = 1;
            continue;
        }
        if (mkdir(path, 0777) != 0) {
            print_error(path);
            any_failure = 1;
            continue;
        }
    }
    return any_failure ? 1 : 0;
}
