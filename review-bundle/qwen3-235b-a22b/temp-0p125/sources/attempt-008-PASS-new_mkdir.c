#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <libgen.h>
#include <errno.h>
#include <unistd.h>

int main(int argc, char **argv) {
    int i = 1;
    i = 1;
    while (i < argc && argv[i][0] == '-') {
        if (strcmp(argv[i], "--") == 0) {
            i++;
            break;
        }
        if (strcmp(argv[i], "-") == 0) {
            break;
        }
        fprintf(stderr, "mkdir: unrecognized option '%s'\nTry 'mkdir --help' for more information.\n", argv[i]);
        return 1;
    }
    if (i >= argc) {
        fprintf(stderr, "mkdir: missing operand\nTry 'mkdir --help' for more information.\n");
        return 1;
    }

    int status = 0;
    for (; i < argc; i++) {
        char *operand = argv[i];
        char *path_dup = strdup(operand);
        if (!path_dup) {
            fprintf(stderr, "mkdir: memory allocation failed\n");
            return 1;
        }
        char *parent = dirname(path_dup);

        // Removed redundant leaf variable handling

        struct stat st;
        if (stat(parent, &st) != 0) {
            if (errno == ENOENT) {
                fprintf(stderr, "mkdir: cannot create directory '%s': No such file or directory\n", operand);
            } else {
                fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", operand, strerror(errno));
            }
            free(path_dup);
            
            status = 1;
            continue;
        }
        if (!S_ISDIR(st.st_mode)) {
            fprintf(stderr, "mkdir: cannot create directory '%s': Not a directory\n", operand);
            free(path_dup);
            
            status = 1;
            continue;
        }

        if (stat(operand, &st) == 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': File exists\n", operand);
            free(path_dup);
            
            status = 1;
            continue;
        } else if (errno != ENOENT) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", operand, strerror(errno));
            free(path_dup);
            
            status = 1;
            continue;
        }

        if (mkdir(operand, 0777) != 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", operand, strerror(errno));
            free(path_dup);
            
            status = 1;
            continue;
        }

        free(path_dup);
        
    }
    return status;
}