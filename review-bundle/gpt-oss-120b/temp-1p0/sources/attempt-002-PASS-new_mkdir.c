#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <limits.h>

/*
 * new_mkdir – create directories according to the spec.
 * Implements minimal behavior without options (except recognizing "--" and unknown options).
 */

static void print_error_missing_operand(void) {
    fprintf(stderr, "mkdir: missing operand\nTry 'mkdir --help' for more information.\n");
}

static void print_error_unknown_option(const char *opt) {
    fprintf(stderr, "mkdir: unrecognized option '%s'\nTry 'mkdir --help' for more information.\n", opt);
}

int main(int argc, char *argv[]) {
    int have_operand = 0;
    int end_of_options = 0;
    int overall_success = 1; // assume success until a failure occurs

    if (argc < 2) {
        print_error_missing_operand();
        return 1;
    }

    for (int i = 1; i < argc; ++i) {
        char *arg = argv[i];
        if (!end_of_options && strcmp(arg, "--") == 0) {
            end_of_options = 1;
            continue;
        }
        if (!end_of_options && arg[0] == '-' && !(strcmp(arg, "-") == 0)) {
            // unknown option
            print_error_unknown_option(arg);
            return 1;
        }
        have_operand = 1; // at least one operand present
        /* Process this operand */
        const char *raw_path = arg;
        /* Strip trailing slashes (but keep single '/' root) */
        size_t raw_len = strlen(raw_path);
        while (raw_len > 1 && raw_path[raw_len-1] == '/') {
            raw_len--;
        }
        char path_buf[PATH_MAX];
        if (raw_len >= sizeof(path_buf)) {
            fprintf(stderr, "mkdir: cannot create directory '%s': File name too long\n", raw_path);
            overall_success = 0;
            continue;
        }
        memcpy(path_buf, raw_path, raw_len);
        path_buf[raw_len] = '\0';
        const char *path = path_buf;
        /* Find parent directory and final component */
        const char *slash = strrchr(path, '/');
        char parent[PATH_MAX];

        if (slash) {
            size_t plen = slash - path; // length of parent part
            if (plen == 0) {
                strcpy(parent, "/");
            } else {
                memcpy(parent, path, plen);
                parent[plen] = '\0';
            }

        } else {
            strcpy(parent, ".");

        }

        /* Verify parent exists and is a directory */
        struct stat st;
        if (stat(parent, &st) != 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
            overall_success = 0;
            continue;
        }
        if (!S_ISDIR(st.st_mode)) {
            fprintf(stderr, "mkdir: cannot create directory '%s': Not a directory\n", path);
            overall_success = 0;
            continue;
        }

        /* Check if final component already exists */
        struct stat dummy;
        if (stat(path, &dummy) == 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': File exists\n", path);
            overall_success = 0;
            continue;
        }

        /* Attempt to create the directory */
        if (mkdir(path, 0777) != 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
            overall_success = 0;
            continue;
        }
    }

    if (!have_operand) {
        print_error_missing_operand();
        return 1;
    }

    return overall_success ? 0 : 1;
}
