#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/stat.h>
#include <limits.h>

static void report_error(const char *path) {
    fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
}

int main(int argc, char *argv[]) {
    int have_operand = 0;
    int any_failure = 0;
    int end_of_options = 0;

    for (int i = 1; i < argc; ++i) {
        const char *arg = argv[i];
        if (!end_of_options) {
            if (strcmp(arg, "--") == 0) { // mark end of options
                end_of_options = 1;
                continue;
            }
            if (arg[0] == '-' && strcmp(arg, "-") != 0) {
                fprintf(stderr, "mkdir: unrecognized option '%s'\nTry 'mkdir --help' for more information.\n", arg);
                return 1;
            }
        }
        // treat as operand
        have_operand = 1;
        const char *path = arg;
        // Create a cleaned version without trailing slashes for processing
        char clean[PATH_MAX];
        strncpy(clean, path, PATH_MAX - 1);
        clean[PATH_MAX - 1] = '\0';
        size_t clen = strlen(clean);
        while (clen > 1 && clean[clen - 1] == '/') {
            clean[--clen] = '\0';
        }

        // split into parent and final component using cleaned path
        const char *slash = strrchr(clean, '/');
        char parent[PATH_MAX];
        const char *final;
        if (slash) {
            size_t plen = slash - clean; // length of parent part
            if (plen == 0) {
                // path like "/foo"
                strcpy(parent, "/");
            } else {
                if (plen >= PATH_MAX) { errno = ENAMETOOLONG; report_error(path); any_failure = 1; continue; }
                memcpy(parent, clean, plen);
                parent[plen] = '\0';
            }
            final = slash + 1;
        } else {
            strcpy(parent, ".");
            final = clean;
        }

        // check parent exists and is directory
        struct stat sb;
        if (stat(parent, &sb) != 0) {
            report_error(path);
            any_failure = 1;
            continue;
        }
        if (!S_ISDIR(sb.st_mode)) {
            errno = ENOTDIR;
            report_error(path);
            any_failure = 1;
            continue;
        }

        // check final component does not already exist
        char full[PATH_MAX];
        if (snprintf(full, sizeof(full), "%s/%s", parent, final) >= (int)sizeof(full)) {
            errno = ENAMETOOLONG;
            report_error(path);
            any_failure = 1;
            continue;
        }
        if (lstat(full, &sb) == 0) { // something exists
            errno = EEXIST;
            report_error(path);
            any_failure = 1;
            continue;
        }
        // attempt to create directory with default mode (0777 masked by umask)
        if (mkdir(full, 0777) != 0) {
            report_error(path);
            any_failure = 1;
            continue;
        }
    }

        if (!have_operand) {
            fprintf(stderr, "mkdir: missing operand\nTry 'mkdir --help' for more information.\n");
            return 1;
        }
    return any_failure ? 1 : 0;
}
