#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/stat.h>
#include <errno.h>

int main(int argc, char *argv[]) {
    int start = 1;
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--") == 0) {
            start = i + 1;
            break;
        } else if (argv[i][0] == '-' && strcmp(argv[i], "-") != 0) {
            fprintf(stderr, "mkdir: unrecognized option '%s'\nTry 'mkdir --help' for more information.\n", argv[i]);
            return 1;
        }
    }

    if (argc <= start) {
        fprintf(stderr, "mkdir: missing operand\nTry 'mkdir --help' for more information.\n");
        return 1;
    }

    int all_success = 1;
    for (int i = start; i < argc; i++) {
        char *path = argv[i];
        size_t len = strlen(path);
        while (len > 0 && path[len - 1] == '/') len--;
        if (len == 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': Invalid argument\n", path);
            all_success = 0;
            continue;
        }

        char *trimmed = strndup(path, len);
        if (!trimmed) {
            fprintf(stderr, "mkdir: memory allocation failed\n");
            exit(1);
        }

        char *last_slash = strrchr(trimmed, '/');
        char parent_path[4096];
        char *final_component;

        if (last_slash) {
            *last_slash = '\0';
            final_component = last_slash + 1;
            if (strlen(trimmed) == 0) {
                snprintf(parent_path, sizeof(parent_path), "/");
            } else {
                snprintf(parent_path, sizeof(parent_path), "%s", trimmed);
            }
        } else {
            snprintf(parent_path, sizeof(parent_path), ".");
            final_component = trimmed;
        }

        struct stat st;
        if (stat(parent_path, &st) != 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
            all_success = 0;
            free(trimmed);
            continue;
        }
        if (!S_ISDIR(st.st_mode)) {
            fprintf(stderr, "mkdir: cannot create directory '%s': Not a directory\n", path);
            all_success = 0;
            free(trimmed);
            continue;
        }

        char full_path[4096];
        snprintf(full_path, sizeof(full_path), "%s/%s", parent_path, final_component);
        if (stat(full_path, &st) == 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': File exists\n", path);
            all_success = 0;
            free(trimmed);
            continue;
        }

        if (mkdir(full_path, 0777) != 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
            all_success = 0;
            free(trimmed);
            continue;
        }

        free(trimmed);
    }

    return all_success ? 0 : 1;
}