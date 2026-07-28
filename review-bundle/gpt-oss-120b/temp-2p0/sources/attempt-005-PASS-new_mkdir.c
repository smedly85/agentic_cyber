#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/stat.h>
#include <unistd.h>

// Helper to print error messages for a specific operand.
static void report_error(const char *path, const char *msg) {
    fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, msg);
}

int main(int argc, char *argv[]) {
    // Argument parsing: support '--' as end of options. No other options are allowed.
    int operand_start = 1; // index of first operand
    int found_double_dash = 0;
    for (int i = 1; i < argc; ++i) {
        if (!found_double_dash && strcmp(argv[i], "--") == 0) {
            found_double_dash = 1;
            operand_start = i + 1;
            continue;
        }
        // If we haven't seen '--' yet, treat arguments beginning with '-'
        if (!found_double_dash && argv[i][0] == '-' && strcmp(argv[i], "-") != 0) {
            // Unknown option
            fprintf(stderr, "mkdir: unrecognized option '%s'\n", argv[i]);
            fprintf(stderr, "Try 'mkdir --help' for more information.\n");
            return 1;
        }
    }

    if (operand_start >= argc) {
        fprintf(stderr, "mkdir: missing operand\n");
        fprintf(stderr, "Try 'mkdir --help' for more information.\n");
        return 1;
    }

    int any_failure = 0;
    for (int i = operand_start; i < argc; ++i) {
        const char *orig_path = argv[i];
        // Create a mutable copy to normalize (strip trailing slashes).
        char *path = strdup(orig_path);
        if (!path) { perror("malloc"); return 1; }
        size_t plen = strlen(path);
        while (plen > 1 && path[plen-1] == '/') {
            path[--plen] = '\0';
        }
        // Determine parent directory of normalized path.
        char *slash = strrchr(path, '/');
        char *parent;
        int need_free = 0;
        if (slash == NULL) {
            parent = "."; // current directory, no allocation needed
        } else if (slash == path) { // leading slash only, i.e., root '/' as parent
            static const char root[] = "/";
            parent = (char *)root;
        } else {
            size_t len = slash - path; // length of parent part
            char *tmp = malloc(len + 1);
            if (!tmp) { perror("malloc"); free(path); return 1; }
            memcpy(tmp, path, len);
            tmp[len] = '\0';
            parent = tmp;
            need_free = 1;
        }

        // Verify parent exists and is a directory.
        struct stat sb;
        if (stat(parent, &sb) != 0) {
            report_error(orig_path, strerror(errno));
            any_failure = 1;
        if (need_free) free(parent);

            continue;
        }
        if (!S_ISDIR(sb.st_mode)) {
            report_error(orig_path, "Not a directory");
            any_failure = 1;
        if (need_free) free(parent);

            continue;
        }

        // Check if final component already exists.
        struct stat sb2;
        if (stat(path, &sb2) == 0) {
            report_error(orig_path, "File exists");
            any_failure = 1;
        if (need_free) free(parent);

            continue;
        }

        // Attempt to create directory with mode 0777 (umask applied by mkdir).
        if (mkdir(path, 0777) != 0) {
            report_error(orig_path, strerror(errno));
            any_failure = 1;
        }

            if (need_free) free(parent);

    }

    return any_failure ? 1 : 0;
}
