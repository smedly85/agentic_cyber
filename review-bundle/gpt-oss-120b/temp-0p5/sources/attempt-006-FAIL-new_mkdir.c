#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/stat.h>
#include <unistd.h>

/*
 * new_mkdir – create one or more directories.
 * Implements minimal behavior for checkpoint 1.
 */

static void print_error(const char *path, const char *msg) {
    // Print in the style: mkdir: cannot create directory 'PATH': REASON
    fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, msg);
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        // No operands at all – handled before any creation.
        fprintf(stderr, "missing operand\n");
        return 1;
    }

    int exit_status = 0; // 0 if all succeed, 1 if any fail.
    int i = 1;
    while (i < argc) {
        char *arg = argv[i];
        // Handle end‑of‑options marker "--"
        if (strcmp(arg, "--") == 0) { i++; continue; }
        // Unknown option handling (starts with '-' but not exactly "-" or "--")
        if (arg[0] == '-' && !(strcmp(arg, "-") == 0)) {
            fprintf(stderr, "unrecognized option '%s'\n", arg);
            return 1;
        }

        // Operand processing – attempt to create directory.
        const char *path = arg;
        // Find last '/' to separate parent and final component.
        const char *slash = strrchr(path, '/');
        if (slash != NULL) {
            size_t parent_len = slash - path; // length of parent part
            if (parent_len == 0) {
                // Path like "/foo" – parent is root, which always exists.
            } else {
                char *parent = strndup(path, parent_len);
                if (!parent) {
                    fprintf(stderr, "memory allocation failure\n");
                    return 1;
                }
                struct stat st;
                if (stat(parent, &st) != 0) {
                    // Parent does not exist.
                    print_error(path, strerror(ENOENT));
                    exit_status = 1;
                    free(parent);
                    i++;
                    continue;
                }
                if (!S_ISDIR(st.st_mode)) {
                    // Parent exists but is not a directory.
                    print_error(path, strerror(ENOTDIR));
                    exit_status = 1;
                    free(parent);
                    i++;
                    continue;
                }
                free(parent);
            }
        } else {
            // No '/' – parent is current working directory, which we assume exists.
        }

        // Check if final component already exists (any type).
        struct stat st_exist;
        if (stat(path, &st_exist) == 0) {
            print_error(path, strerror(EEXIST));
            exit_status = 1;
            i++;
            continue;
        }

        // Attempt to create directory with default mode (mkdir respects umask).
        if (mkdir(path, 0777) != 0) {
            // Preserve the system error message.
            print_error(path, strerror(errno));
            exit_status = 1;
            i++;
            continue;
        }

        // Success – nothing to output.
        i++;
    }

    return exit_status;
}
