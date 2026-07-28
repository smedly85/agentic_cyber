#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <errno.h>
#include <limits.h>

int main(int argc, char *argv[]) {
    const char *prog_name = "mkdir";

    if (argc < 2) {
        // No arguments at all
        fprintf(stderr, "%s: missing operand\nTry '%s --help' for more information.\n", prog_name, prog_name);
        return 1;
    }

    int any_failure = 0;
    int end_of_options = 0;
    int operand_count = 0;

    for (int i = 1; i < argc; ++i) {
        char *arg = argv[i];
        if (!end_of_options && strcmp(arg, "--") == 0) {
            end_of_options = 1;
            continue;
        }
        if (!end_of_options && arg[0] == '-' && !(strcmp(arg, "-") == 0)) {
            // Unknown option
                    fprintf(stderr, "%s: unrecognized option '%s'\nTry '%s --help' for more information.\n", prog_name, arg, prog_name);
            return 1;
        }
        // Operand (including a bare '-')
        operand_count++;
        char clean_path[PATH_MAX];
        strncpy(clean_path, arg, PATH_MAX - 1);
        clean_path[PATH_MAX - 1] = '\0';
        size_t clean_len = strlen(clean_path);

        while (clean_len > 1 && clean_path[clean_len - 1] == '/') {
            clean_path[--clean_len] = '\0';
        }
        const char *path = clean_path;
        // Debug print final path
        //fprintf(stderr, "FINAL PATH='%s'\n", path);



        // Debug: ensure trailing slash trimmed



        /* Determine parent directory */
        const char *slash = strrchr(path, '/');
        char parent[PATH_MAX];
        if (slash) {
            size_t len = slash - path; // length of parent part
            if (len == 0) {
                // Path starts with '/', parent is root "/"
                strcpy(parent, "/");
            } else {
                memcpy(parent, path, len);
                parent[len] = '\0';
            }
        } else {
            // No slash -> parent is current directory
            strcpy(parent, ".");
        }

        struct stat st;
        if (stat(parent, &st) != 0) {
            /* Parent does not exist */
                    fprintf(stderr, "%s: cannot create directory '%s': %s\n", prog_name, path, strerror(errno));
            any_failure = 1;
            continue;
        }
        if (!S_ISDIR(st.st_mode)) {
            errno = ENOTDIR;
                    fprintf(stderr, "%s: cannot create directory '%s': %s\n", prog_name, path, strerror(errno));
            any_failure = 1;
            continue;
        }

        /* Check if final component already exists */
        struct stat dummy;
        if (lstat(path, &dummy) == 0) {
            errno = EEXIST;
                    fprintf(stderr, "%s: cannot create directory '%s': %s\n", prog_name, path, strerror(errno));
            any_failure = 1;
            continue;
        }

        /* Attempt to create the directory */
        if (mkdir(path, 0777) != 0) {
                    fprintf(stderr, "%s: cannot create directory '%s': %s\n", prog_name, path, strerror(errno));
            any_failure = 1;
            continue;
        }
    }

    if (operand_count == 0) {
        // No operands after option processing
        fprintf(stderr, "%s: missing operand\nTry '%s --help' for more information.\n", prog_name, prog_name);
        return 1;
    }

    return any_failure ? 1 : 0;
}
