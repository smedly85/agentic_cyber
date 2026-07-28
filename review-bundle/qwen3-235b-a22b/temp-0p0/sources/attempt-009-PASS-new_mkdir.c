#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>
#include <errno.h>
#include <limits.h>

int main(int argc, char **argv) {
    int i = 1;

    for (; i < argc; i++) {
        if (strcmp(argv[i], "--") == 0) {
            i++;
            break;
        }
        if (argv[i][0] == '-' && strcmp(argv[i], "-") != 0) {
            fprintf(stderr, "mkdir: unrecognized option '%s'\nTry 'mkdir --help' for more information.\n", argv[i]);
            return 1;
        }
        break;
    }

    if (i >= argc) {
        fprintf(stderr, "mkdir: missing operand\nTry 'mkdir --help' for more information.\n");
        return 1;
    }

    int success = 1;
    for (int j = i; j < argc; j++) {
        char *orig_path = argv[j];
        char path[PATH_MAX];
        strncpy(path, orig_path, PATH_MAX-1);
        path[PATH_MAX-1] = '\0';

        // Remove trailing slashes
        size_t len = strlen(path);
        while (len > 0 && path[len-1] == '/') {
            len--;
        }
        path[len] = '\0';
        if (len == 0) {
            strcpy(path, "/");
        }

        // Skip normalized_path duplicate handling
        struct stat sb;

        if (strlen(path) >= PATH_MAX) {
            fprintf(stderr, "mkdir: cannot create directory '%s': Path too long\n", path);
            success = 0;
            continue;
        }
        char fullpath[PATH_MAX];
        strcpy(fullpath, path);

        char *last_slash = strrchr(fullpath, '/');
        char parent[PATH_MAX];
        if (last_slash == NULL) {
            strcpy(parent, ".");
        } else {
            *last_slash = '\0';
            strcpy(parent, fullpath);
            if (strlen(parent) == 0) {
                strcpy(parent, "/");
            }
        }

        if (stat(parent, &sb) != 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
            success = 0;
            continue;
        }

        if (!S_ISDIR(sb.st_mode)) {
            fprintf(stderr, "mkdir: cannot create directory '%s': Not a directory\n", path);
            success = 0;
            continue;
        }

        if (stat(path, &sb) == 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': File exists\n", path);
            success = 0;
            continue;
        } else if (errno != ENOENT) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
            success = 0;
            continue;
        }

        if (mkdir(path, 0777) != 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
            success = 0;
            continue;
        }
    }

    return success ? 0 : 1;
}