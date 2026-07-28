#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <libgen.h>
#include <sys/stat.h>
#include <errno.h>
#include <unistd.h>

int main(int argc, char *argv[]) {
    int operand_count = 0;
    char *operands[512];

    // Parse operands and validate options
    for (int i = 1; i < argc; i++) {
        if (argv[i][0] == '-') {
            if (argv[i][1] == '\0') {
                operands[operand_count++] = argv[i];
            } else if (strcmp(argv[i], "--") == 0) {
                for (int j = i + 1; j < argc; j++) operands[operand_count++] = argv[j];
                break;
            } else {
                 fprintf(stderr, "mkdir: unrecognized option '%s'\nTry 'mkdir --help' for more information.\n", argv[i]);
                return 1;
            }
        } else {
            operands[operand_count++] = argv[i];
        }
    }

    // Handle no operands case
    if (operand_count == 0) {
        fprintf(stderr, "mkdir: missing operand\nTry 'mkdir --help' for more information.\n");
        return 1;
    }

    int errors = 0;
    for (int i = 0; i < operand_count; i++) {
        char *operand = operands[i];
        char *path_dup = strdup(operand);
        if (!path_dup) {
            perror("new_mkdir");
            exit(1);
        }
        char *parent = dirname(path_dup);
        char *base_dup = strdup(operand);
        if (!base_dup) {
            perror("new_mkdir");
            free(path_dup);
            exit(1);
        }
        char *base = basename(base_dup);

        // Skip invalid operands
        if (base[0] == '\0') {
            fprintf(stderr, "mkdir: cannot create directory '%s': Invalid operand\n", operand);
            errors++;
            goto cleanup;
        }

        struct stat sb;
        // Check parent directory existence
        if (stat(parent, &sb) != 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", operand, strerror(errno));
            errors++;
            goto cleanup;
        }
        // Validate parent is a directory
        if (!S_ISDIR(sb.st_mode)) {
            fprintf(stderr, "mkdir: cannot create directory '%s': Not a directory\n", operand);
            errors++;
            goto cleanup;
        }

        // Construct full path
        char *full_path = malloc(strlen(parent) + strlen(base) + 2);
        if (!full_path) {
            perror("new_mkdir");
            goto cleanup;
        }
        strcpy(full_path, parent);
        strcat(full_path, "/");
        strcat(full_path, base);

        // Check if target already exists
        if (stat(full_path, &sb) == 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': File exists\n", operand);
            errors++;
            free(full_path);
            goto cleanup;
        }

        // Create directory
        if (mkdir(full_path, 0777) != 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", operand, strerror(errno));
            errors++;
        }

        free(full_path);
cleanup:
        free(path_dup);
        free(base_dup);
    }
    return errors ? 1 : 0;
}