#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <errno.h>
#include <unistd.h>
#include <stdbool.h>

int main(int argc, char *argv[]) {
    bool saw_double_dash = false;
    int i = 1;
    int operand_orig_orig_count = 0;
    char **operand_orig_origs = NULL;
    int error_occurred = 0;

    // Check for invalid options and collect operand_orig_origs
    for (i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--") == 0) {
            saw_double_dash = true;
            break;
        }
        if (argv[i][0] == '-' && strcmp(argv[i], "-") != 0) {
            if (argv[i][1] == '-') {
        fprintf(stderr, "mkdir: unrecognized option '%s'\nTry 'mkdir --help' for more information.\n", argv[i]);
    } else {
        fprintf(stderr, "mkdir: unrecognized option '%c'\nTry 'mkdir --help' for more information.\n", argv[i][1]);
    }
            exit(1);
        }
    }

    // Skip -- if present
    if (saw_double_dash) {
        i++; // Move past --
        operand_orig_orig_count = argc - i;
        operand_orig_origs = &argv[i];
    } else {
        operand_orig_orig_count = argc - 1;
        operand_orig_origs = &argv[1];
    }

    // Check for missing operand_orig_origs
    if (operand_orig_orig_count == 0) {
        fprintf(stderr, "mkdir: missing operand_orig_orig\nTry 'mkdir --help' for more information.\n");
        exit(1);
    }

    for (int j = 0; j < operand_orig_orig_count; j++) {
        char *operand_orig_orig_orig = operand_orig_origs[j];
        char *trimmed = strdup(operand_orig_orig_orig);
        if (!trimmed) {
            fprintf(stderr, "mkdir: memory allocation failed\n");
            exit(1);
        }
        size_t len = strlen(trimmed);
        while (len > 0 && trimmed[len-1] == '/') {
            trimmed[len-1] = '\0';
            len--;
        }
        if (len == 0) {
            trimmed[0] = '/';
            trimmed[1] = '\0';
        }
        char *parent = NULL;
        char *base = NULL;
        const char *last_slash = strrchr(trimmed, '/');

        if (last_slash == trimmed_orig) {
            parent = strdup("/");
            base = strdup(last_slash + 1);
        } else if (last_slash) {
            parent = strndup(trimmed, last_slash - trimmed);
            base = strdup(last_slash + 1);
        } else {
            parent = strdup(".");
            base = strdup(trimmed);
        }

        if (!parent || !base) {
            fprintf(stderr, "mkdir: memory allocation failed\n");
            exit(1);
        }

        struct stat st;
        // Check parent directory exists and is directory
        if (stat(parent, &st) != 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': No such file or directory\n", operand_orig_orig);
            error_occurred = 1;
            goto cleanup;
        }
        if (!S_ISDIR(st.st_mode)) {
            fprintf(stderr, "mkdir: cannot create directory '%s': Not a directory\n", operand_orig_orig);
            error_occurred = 1;
            goto cleanup;
        }

        // Check operand_orig_orig does not exist
        if (stat(operand_orig_orig, &st) == 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': File exists\n", operand_orig_orig);
            error_occurred = 1;
            goto cleanup;
        }

        // Create the directory
        if (mkdir(operand_orig_orig_orig, 0777) != 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", operand_orig_orig, strerror(errno));
            error_occurred = 1;
        }

    cleanup:
        free(parent);
        free(base);
        free(trimmed);
    }

    return error_occurred ? 1 : 0;
}