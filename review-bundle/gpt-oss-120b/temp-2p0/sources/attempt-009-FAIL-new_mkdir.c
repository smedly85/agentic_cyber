#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/stat.h>
#include <unistd.h>

static int process_path(const char *path) {
    // Find last '/' to separate parent and final component
    const char *slash = strrchr(path, '/');
    char *parent = NULL;
    if (slash) {
        size_t plen = slash - path;
        parent = malloc(plen + 1);
        if (!parent) {
            fprintf(stderr, "new_mkdir: memory allocation failed\n");
            return 1;
        }
        memcpy(parent, path, plen);
        parent[plen] = '\0';
    } else {
        // No slash -> parent is current directory "."
        parent = strdup(".");
        if (!parent) {
            fprintf(stderr, "new_mkdir: memory allocation failed\n");
            return 1;
        }
    }

    // Verify parent exists and is a directory
    struct stat sb;
    if (stat(parent, &sb) != 0) {
        // Parent does not exist or cannot be accessed
        fprintf(stderr, "new_mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
        free(parent);
        return 1;
    }
    if (!S_ISDIR(sb.st_mode)) {
        // Not a directory
        fprintf(stderr, "new_mkdir: cannot create directory '%s': %s\n", path, "Not a directory");
        free(parent);
        return 1;
    }
    free(parent);

    // Check if final component already exists
    struct stat exist;
    if (lstat(path, &exist) == 0) {
        fprintf(stderr, "new_mkdir: cannot create directory '%s': %s\n", path, "File exists");
        return 1;
    }

    // Attempt to create the directory with default mode (0777 masked by umask)
    if (mkdir(path, 0777) != 0) {
        fprintf(stderr, "new_mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
        return 1;
    }
    return 0; // success
}

int main(int argc, char *argv[]) {
    int any_failure = 0;
    int have_operand = 0;
    for (int i = 1; i < argc; ++i) {
        const char *arg = argv[i];
        if (!have_operand && strcmp(arg, "--") == 0) {
            // End of options marker, skip it
            continue;
        }
        // Option detection (unknown option handling)
        if (!have_operand && arg[0] == '-' && !(strcmp(arg, "-") == 0)) {
            fprintf(stderr, "new_mkdir: unknown option '%s'\n", arg);
            return 1;
        }
        have_operand = 1;
        // Process this operand
        if (process_path(arg) != 0) {
            any_failure = 1;
        }
    }

    if (!have_operand) {
        fprintf(stderr, "new_mkdir: missing operand\n");
        return 1;
    }
    return any_failure ? 1 : 0;
}
