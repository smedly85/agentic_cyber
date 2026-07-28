#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>
#include <errno.h>
#include <limits.h>

int main(int argc, char *argv[]) {
    argc--;
    argv++;

    int operand_count = 0;
    char **operands = NULL;
    int i;

    for (i = 0; i < argc; i++) {
        if (strcmp(argv[i], "--") == 0) {
            while (++i < argc) {
                operand_count++;
                char **tmp = realloc(operands, operand_count * sizeof(char *));
                if (!tmp) {
                    free(operands);
                    fprintf(stderr, "mkdir: memory allocation failed\n");
                    exit(1);
                }
                operands = tmp;
                operands[operand_count-1] = argv[i];
            }
            break;
        } else if (argv[i][0] == '-' && argv[i][1] != '\0') {
if (argv[i][1] == '-') {
        fprintf(stderr, "mkdir: unrecognized option '%s'\nTry 'mkdir --help' for more information.\n", argv[i]);
    } else {
        fprintf(stderr, "mkdir: invalid option -- '%s'\nTry 'mkdir --help' for more information.\n", argv[i] + 1);
    }
    exit(1);
        } else {
            operand_count++;
            char **tmp = realloc(operands, operand_count * sizeof(char *));
            if (!tmp) {
                free(operands);
                fprintf(stderr, "mkdir: memory allocation failed\n");
                exit(1);
            }
            operands = tmp;
            operands[operand_count-1] = argv[i];
        }
    }

    if (operand_count == 0) {
fprintf(stderr, "mkdir: missing operand\nTry 'mkdir --help' for more information.\n");
    exit(1);
    }

    int failure = 0;

    for (i = 0; i < operand_count; i++) {
        char *path = operands[i];
        char *copy = strdup(path);
    if (copy) {
        size_t len = strlen(copy);
        while (len > 1 && copy[len-1] == '/') {
            copy[--len] = '\0';
        }
    }
        if (!copy) {
            fprintf(stderr, "mkdir: memory allocation failed\n");
            exit(1);
        }

        char *base = strrchr(copy, '/');
        if (base) {
            *base = '\0';
            base++;
        } else {
            base = copy;
        }
        char *dir = (base == copy) ? "." : copy;

        struct stat st;
        if (stat(dir, &st) != 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
            failure = 1;
            free(copy);
            continue;
        }
        if (!S_ISDIR(st.st_mode)) {
            fprintf(stderr, "mkdir: cannot create directory '%s': Not a directory\n", path);
            failure = 1;
            free(copy);
            continue;
        }

        char full_path[PATH_MAX];
        if (strcmp(dir, ".") == 0) {
            snprintf(full_path, sizeof(full_path), "%s", base);
        } else {
            snprintf(full_path, sizeof(full_path), "%s/%s", dir, base);
        }

        if (stat(full_path, &st) == 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': File exists\n", path);
            failure = 1;
            free(copy);
            continue;
        }

        if (mkdir(full_path, 0777) != 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
            failure = 1;
        }

        free(copy);
    }

    free(operands);
    exit(failure ? 1 : 0);
}