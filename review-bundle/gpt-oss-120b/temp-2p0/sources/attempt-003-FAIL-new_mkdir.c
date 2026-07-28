#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/stat.h>
#include <stddef.h>
#include <stdbool.h>
#define BUF_SIZE 4096




int main(int argc, char *argv[]) {
    if (argc == 1) {
        fprintf(stderr, "new_mkdir: missing operand\n");
        return 1;
    }

    int first_operand = -1;
    bool end_of_options = false;
    for (int i = 1; i < argc; ++i) {
        if (!end_of_options && strcmp(argv[i], "--") == 0) {
            end_of_options = true;
            continue;
        }
        if (!end_of_options && argv[i][0] == '-' && !(argv[i][1] == '\0')) { // unknown option
            fprintf(stderr, "new_mkdir: unrecognized option '%s'\n", argv[i]);
            return 1;
        }
        // operand
        if (first_operand == -1) {
            first_operand = i;
        }
    }

    if (first_operand == -1) {
        fprintf(stderr, "new_mkdir: missing operand\n");
        return 1;
    }

    bool any_failure = false;
    for (int i = first_operand; i < argc; ++i) {
        const char *arg = argv[i];
        if (strcmp(arg, "--") == 0)
            continue; // not an operand

        // Split into parent and leaf component
        const char *slash = strrchr(arg, '/');
        char parent[BUF_SIZE] = {0};
        char leaf[BUF_SIZE];
        if (slash) {
            size_t plen = slash - arg;
            if (plen >= sizeof(parent)) {
                fprintf(stderr, "new_mkdir: path too long '%s'\n", arg);
                any_failure = true;
                continue;
            }
            memcpy(parent, arg, plen);
            parent[plen] = '\0';
            strncpy(leaf, slash + 1, sizeof(leaf) - 1);
        } else {
            /* No slash: parent is empty, leaf is the whole argument */
            parent[0] = '\0';
            strncpy(leaf, arg, sizeof(leaf) - 1);
            leaf[sizeof(leaf) - 1] = '\0';
        }


        // Verify parent directory (if any)
        struct stat st;
        if (parent[0] != '\0') {
            if (lstat(parent, &st) != 0) {
                fprintf(stderr, "new_mkdir: cannot create directory '%s': %s\n", arg, strerror(errno));
                any_failure = true;
                continue;
            }
            if (!S_ISDIR(st.st_mode)) {
                fprintf(stderr, "new_mkdir: cannot create directory '%s': Not a directory\n", arg);
                any_failure = true;
                continue;
            }
        }

        // Build the full path for the new directory
        char fullpath[BUF_SIZE];
        if (parent[0] != '\0') {
            snprintf(fullpath, sizeof(fullpath), "%s/%s", parent, leaf);
        } else {
            snprintf(fullpath, sizeof(fullpath), "%s", leaf);
        }

        // Check whether the target already exists
        if (lstat(fullpath, &st) == 0) {
            fprintf(stderr, "new_mkdir: cannot create directory '%s': File exists\n", arg);
            any_failure = true;
            continue;
        }

        // Attempt to create the directory with default mode (masked by umask)
        if (mkdir(fullpath, 0777) != 0) {
            fprintf(stderr, "new_mkdir: cannot create directory '%s': %s\n", arg, strerror(errno));
            any_failure = true;
            continue;
        }
    }

    return any_failure ? 1 : 0;
}
