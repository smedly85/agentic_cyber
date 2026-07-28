#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/stat.h>
#include <unistd.h>

/* Print errors in the exact format required by tests */
static void print_error(const char *path, const char *msg) {
    fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, msg);
}

int main(int argc, char *argv[]) {
    int exit_status = 0; // 0 if all succeed, 1 otherwise
    int have_operand = 0;
    int i = 1;
    int end_of_options = 0;

    while (i < argc) {
        const char *arg = argv[i];
        if (!end_of_options && strcmp(arg, "--") == 0) {
            end_of_options = 1;
            i++;
            continue;
        }
        if (!end_of_options && arg[0] == '-' && !(strcmp(arg, "-") == 0)) {
            /* Unknown option */
            fprintf(stderr, "mkdir: unrecognized option '%s'\nTry 'mkdir --help' for more information.\n", arg);
            return 1;
        }
        // Operand
        have_operand = 1;
        /* Make a mutable copy of the operand and normalize it */
        char *path_copy = strdup(arg);
        if (!path_copy) {
            fprintf(stderr, "%s: memory allocation failed\n", argv[0]);
            return 1;
        }
        /* Remove trailing '/' characters (but keep a single '/' for root) */
        size_t plen = strlen(path_copy);
        while (plen > 1 && path_copy[plen - 1] == '/') {
            path_copy[--plen] = '\0';
        }
        const char *path = path_copy; /* use normalized path */
        /* Determine parent directory */
        char *sep = strrchr(path, '/');
        char *parent_path;
        if (sep == NULL) {
            /* No '/' in the operand: parent is the current directory */
            const char *cwd = ".";
            size_t len = 1;
            parent_path = malloc(len + 1);
            if (!parent_path) {
                fprintf(stderr, "%s: memory allocation failed\n", argv[0]);
                free(path_copy);
                return 1;
            }
            memcpy(parent_path, cwd, len);
            parent_path[len] = '\0';
        } else if (sep == path) {
            // Path like /foo -> parent is "/"
            size_t len = 1; // just '/'
            parent_path = malloc(len + 1);
            if (!parent_path) {
                fprintf(stderr, "%s: memory allocation failed\n", argv[0]);
                return 1;
            }
            memcpy(parent_path, "/", 1);
            parent_path[1] = '\0';
        } else {
            size_t len = sep - path; // length of parent part
            parent_path = malloc(len + 1);
            if (!parent_path) {
                fprintf(stderr, "%s: memory allocation failed\n", argv[0]);
                return 1;
            }
            memcpy(parent_path, path, len);
            parent_path[len] = '\0';
        }

        struct stat sb;
        if (stat(parent_path, &sb) != 0) {
            // Parent does not exist or cannot be accessed
            print_error(path, strerror(errno));
            exit_status = 1;
            free(parent_path);
            free(path_copy);
            i++;
            continue;
        }
        if (!S_ISDIR(sb.st_mode)) {
            // Parent exists but is not a directory
            print_error(path, "Not a directory");
            exit_status = 1;
            free(parent_path);
            free(path_copy);
            i++;
            continue;
        }
        free(parent_path);

        /* Check if final component already exists */
        if (stat(path, &sb) == 0) {
            print_error(path, "File exists");
            exit_status = 1;
            free(path_copy);
            i++;
            continue;
        }
        /* Try to create directory */
        if (mkdir(path, 0777) != 0) {
            print_error(path, strerror(errno));
            exit_status = 1;
            free(path_copy);
            i++;
            continue;
        }
        // success for this operand
        free(path_copy);
        i++;
    }

    if (!have_operand) {
        fprintf(stderr, "mkdir: missing operand\nTry 'mkdir --help' for more information.\n");
        return 1;
    }
    return exit_status;
}
