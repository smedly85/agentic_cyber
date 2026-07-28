#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>
#include <limits.h>

int main(int argc, char *argv[]) {
    int i = 1;
    int end_of_options = 0;
    char **operands = NULL;
    int num_operands = 0;
    int had_error = 0;

    for (; i < argc; i++) {
        if (strcmp(argv[i], "--") == 0) {
            end_of_options = 1;
            continue;
        }
        if (!end_of_options && argv[i][0] == '-' && argv[i][1] != '\0') {
            if (strcmp(argv[i], "-") != 0) {
                fprintf(stderr, "mkdir: unrecognized option '%s'\nTry 'mkdir --help' for more information.\n", argv[i]);
                return 1;
            }
        }
        operands = realloc(operands, (num_operands + 1) * sizeof(char*));
        if (!operands) {
            fprintf(stderr, "new_mkdir: memory allocation failed\n");
            return 1;
        }
        operands[num_operands++] = argv[i];
    }

    if (num_operands == 0) {
        fprintf(stderr, "mkdir: missing operand\nTry 'mkdir --help' for more information.\n");
        free(operands);
        return 1;
    }

    for (int j = 0; j < num_operands; j++) {
        char *orig_path = operands[j];
        char local_path[PATH_MAX];
        strncpy(local_path, orig_path, sizeof(local_path));
        local_path[sizeof(local_path) - 1] = '\0';
        size_t len = strlen(local_path);
        if (len > 1) {
            while (local_path[len - 1] == '/' && len > 1) {
                local_path[len - 1] = '\0';
                len--;
            }
        }
        char *path = local_path;
        char parent[PATH_MAX];
        char base[PATH_MAX];
        char *last_slash = strrchr(path, '/');

        if (last_slash != NULL) {
            if (last_slash == path) {
                strcpy(parent, "/");
                strcpy(base, last_slash + 1);
            } else {
                size_t len = last_slash - path;
                strncpy(parent, path, len);
                parent[len] = '\0';
                strcpy(base, last_slash + 1);
            }
        } else {
            strcpy(parent, ".");
            strcpy(base, path);
        }

        if (base[0] == '\0') {
            fprintf(stderr, "new_mkdir: cannot create directory '%s': No such file or directory\n", path);
            had_error = 1;
            continue;
        }

        struct stat st;
        if (stat(parent, &st) != 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
            had_error = 1;
            continue;
        }
        if (!S_ISDIR(st.st_mode)) {
            fprintf(stderr, "mkdir: cannot create directory '%s': Not a directory\n", path);
            had_error = 1;
            continue;
        }

        if (stat(path, &st) == 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': File exists\n", path);
            had_error = 1;
            continue;
        }

        if (mkdir(path, 0777) != 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
            had_error = 1;
        }
    }

    free(operands);
    return had_error ? 1 : 0;
}