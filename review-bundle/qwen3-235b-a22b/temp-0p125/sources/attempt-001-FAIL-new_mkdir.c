#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>
#include <libgen.h>

int main(int argc, char *argv[]) {
    int operand_count = 0;
    char **operands = NULL;
    int after_end = 0;

    for (int i = 1; i < argc; i++) {
        if (after_end) {
            operands = realloc(operands, (operand_count + 1) * sizeof(char*));
            if (!operands) { fprintf(stderr, "mkdir: out of memory\n"); exit(1); }
            operands[operand_count++] = argv[i];
        } else {
            if (strcmp(argv[i], "--") == 0) {
                after_end = 1;
            } else if (argv[i][0] == '-' && strcmp(argv[i], "-") != 0) {
                fprintf(stderr, "mkdir: unrecognized option '%s'\nTry 'mkdir --help' for more information.\n", argv[i] + 1);
                exit(1);
            } else {
                operands = realloc(operands, (operand_count + 1) * sizeof(char*));
                if (!operands) { fprintf(stderr, "mkdir: out of memory\n"); exit(1); }
                operands[operand_count++] = argv[i];
            }
        }
    }

    if (operand_count == 0) {
        fprintf(stderr, "mkdir: missing operand\nTry 'mkdir --help' for more information.\n");
        exit(1);
    }

    int error_count = 0;
    for (int i = 0; i < operand_count; i++) {
        char *path = operands[i];
        char *trimmed = strdup(path);
        if (!trimmed) {
            fprintf(stderr, "mkdir: out of memory\n");
            free(operands);
            return 1;
        }
        size_t len = strlen(trimmed);
        while (len > 0 && trimmed[len-1] == '/') {
            len--;
        }
        trimmed[len] = '\0';
        char *last_slash = strrchr(trimmed, '/');
        char *parent;
        char *final;
        if (last_slash != NULL) {
            parent = strndup(trimmed, last_slash - trimmed);
            final = strdup(last_slash + 1);
        } else {
            parent = strdup(".");
            final = strdup(trimmed);
        }
        free(trimmed);
        if (!parent || !final) {
            fprintf(stderr, "mkdir: out of memory\n");
            free(parent); free(final);
            exit(1);
        }
        struct stat st;



        if (stat(parent, &st) != 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
            free(parent); free(final);
            error_count++; continue;
        }

        if (!S_ISDIR(st.st_mode)) {
            fprintf(stderr, "mkdir: cannot create directory '%s': Not a directory\n", path);
            free(parent); free(final);
            error_count++; continue;
        }

        if (stat(trimmed, &st) == 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': File exists\n", path);
            free(parent); free(final);
            error_count++; continue;
        }

        if (mkdir(trimmed, 0777) != 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
            free(parent); free(final);
            error_count++; continue;
        }

        free(parent); free(final);
    }

    free(operands);
    return error_count ? 1 : 0;
}