#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
#include <errno.h>

int main(int argc, char *argv[]) {
    int operands_start = 1;

    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--") == 0) {
            operands_start = i + 1;
            break;
        } else if (argv[i][0] == '-' && strcmp(argv[i], "-") != 0) {
            fprintf(stderr, "mkdir: unrecognized option '%s'\nTry 'mkdir --help' for more information.\n", argv[i]);
            return 1;
        }
    }

    if (operands_start >= argc) {
        fprintf(stderr, "mkdir: missing operand\nTry 'mkdir --help' for more information.\n");
        return 1;
    }

    int all_success = 1;
    for (int i = operands_start; i < argc; i++) {
        char *path = argv[i];
        char *trimmed_path = strdup(path);
        size_t len = strlen(trimmed_path);
        while (len > 0 && trimmed_path[len - 1] == '/') {
            trimmed_path[len - 1] = '\0';
            len = strlen(trimmed_path);
        }
        char *last_slash = strrchr(trimmed_path, '/');
        char *parent, *leaf;

        if (last_slash) {
            if (last_slash == trimmed_path) {
                parent = strdup("/");
                leaf = strdup(trimmed_path + 1);
            } else {
                parent = strndup(trimmed_path, last_slash - trimmed_path);
                leaf = strdup(last_slash + 1);
            }
        } else {
            parent = strdup(".");
            leaf = strdup(trimmed_path);
        }

        if (!parent || !leaf) {
            fprintf(stderr, "new_mkdir: out of memory\n");
            exit(1);
        }

        struct stat st;
        if (stat(parent, &st) != 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
            all_success = 0;
        } else if (!S_ISDIR(st.st_mode)) {
            fprintf(stderr, "mkdir: cannot create directory '%s': Not a directory\n", path);
            all_success = 0;
        } else if (stat(path, &st) == 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': File exists\n", path);
            all_success = 0;
        } else if (mkdir(path, 0777) != 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
            all_success = 0;
        }

        free(parent);
        free(leaf);
    }

    return all_success ? 0 : 1;
}