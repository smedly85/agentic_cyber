#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/stat.h>
#include <unistd.h>
#include <stdbool.h>

/*
 * new_mkdir - create directories (no options).
 * Implements behavior described in the task prompt.
 */

static void print_error(const char *prog, const char *path, const char *msg) {
    // Format matches GNU mkdir style: "mkdir: cannot create directory 'PATH': REASON"
    fprintf(stderr, "%s: cannot create directory '%s': %s\n", prog, path, msg);
}

int main(int argc, char *argv[]) {
    const char *prog_name = argv[0];
    int have_operand = 0;
    int status = 0; // overall exit status (0 if all succeed, 1 otherwise)

    for (int i = 1; i < argc; ++i) {
        const char *arg = argv[i];
        // Handle end‑of‑options marker '--'
        static bool after_dashdash = false; // track if we have seen '--'
        if (strcmp(arg, "--") == 0) {
            after_dashdash = true;
            continue; // skip marker, not an operand
        }
        // After handling '--' and unknown options, normalize the operand by stripping trailing slashes (except when the argument is exactly "/").
        const char *norm_arg = arg;
        if (strlen(arg) > 1) {
            // Make a mutable copy to trim.
            char *tmp_norm = strdup(arg);
            if (!tmp_norm) {
                fprintf(stderr, "%s: memory allocation failed\n", prog_name);
                return 1;
            }
            size_t len = strlen(tmp_norm);
            while (len > 1 && tmp_norm[len - 1] == '/') {
                tmp_norm[--len] = '\0';
            }
            norm_arg = tmp_norm; // use trimmed version for processing
        }
        // Use norm_arg in place of arg for the rest of the loop.
        const char *process_path = norm_arg;

        have_operand = 1;

        /* Split path into parent and leaf components. */
        const char *slash = strrchr(process_path, '/');
        const char *parent_path;
        const char *leaf;
        bool need_free_parent = false;
        if (slash) {
            size_t parent_len = slash - process_path;
            if (parent_len == 0) {
                parent_path = "/"; // root directory
            } else {
                char *tmp = malloc(parent_len + 1);
                if (!tmp) { fprintf(stderr, "%s: memory allocation failed\n", prog_name); return 1; }
                memcpy(tmp, process_path, parent_len);
                tmp[parent_len] = '\0';
                parent_path = tmp;
                need_free_parent = true;
            }
            leaf = slash + 1; // may be empty string for trailing '/'
        } else {
            parent_path = ".";
            leaf = process_path;
        }


        // Empty leaf (e.g., path ending with '/') is treated as error similar to existing component.
        if (leaf[0] == '\0') {
            print_error(prog_name, arg, "Invalid argument");
            status = 1;
            if (need_free_parent) free((void *)parent_path);
            continue;
        }

        // Verify parent exists and is a directory.
        struct stat st;
        if (stat(parent_path, &st) != 0) {
            print_error(prog_name, arg, strerror(errno));
            status = 1;
            if (need_free_parent) free((void *)parent_path);
            continue;
        }
        if (!S_ISDIR(st.st_mode)) {
            print_error(prog_name, arg, "Not a directory");
            status = 1;
            if (need_free_parent) free((void *)parent_path);
            continue;
        }

        // Check that leaf does not already exist.
        char *full_path;
        if (strcmp(parent_path, "/") == 0) {
            full_path = malloc(1 + strlen(leaf) + 1); // '/' + leaf + '\0'
            if (!full_path) { fprintf(stderr, "%s: memory allocation failed\n", prog_name); return 1; }
            sprintf(full_path, "/%s", leaf);
        } else {
            size_t len = strlen(parent_path) + 1 + strlen(leaf) + 1;
            full_path = malloc(len);
            if (!full_path) { fprintf(stderr, "%s: memory allocation failed\n", prog_name); return 1; }
            sprintf(full_path, "%s/%s", parent_path, leaf);
        }

        // If path already exists (any type), fail.
        if (stat(full_path, &st) == 0) {
            print_error(prog_name, arg, "File exists");
            status = 1;
            free(full_path);
            if (need_free_parent) free((void *)parent_path);
            continue;
        }

        // Attempt to create directory with default mode (respecting umask).
        if (mkdir(full_path, 0777) != 0) {
            print_error(prog_name, arg, strerror(errno));
            status = 1;
        }
                // Clean up.
        free(full_path);
        if (need_free_parent) free((void *)parent_path);
    }

    if (!have_operand) {
        fprintf(stderr, "%s: missing operand\nTry 'mkdir --help' for more information.\n", prog_name);

        return 1;
    }
    return status;
}
