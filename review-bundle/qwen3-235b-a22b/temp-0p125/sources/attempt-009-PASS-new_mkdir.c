#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <limits.h>
#include <unistd.h>

int main(int argc, char *argv[]) {
    int optind = 1;
    int end_of_options = 0;

    while (optind < argc && argv[optind][0] == '-' && !end_of_options) {
        if (strcmp(argv[optind], "--") == 0) {
            optind++;
            end_of_options = 1;
            break;
        }
        if (strcmp(argv[optind], "-") == 0) break;
        fprintf(stderr, "mkdir: unrecognized option '%s'\nTry 'mkdir --help' for more information.\n", argv[optind]);
        return 1;
    }

    if (optind >= argc) {
        fprintf(stderr, "mkdir: missing operand\nTry 'mkdir --help' for more information.\n");
        return 1;
    }

    int any_failure = 0;
    for (int i = optind; i < argc; i++) {
         char buf[PATH_MAX];
         strncpy(buf, argv[i], PATH_MAX);
         buf[PATH_MAX - 1] = '\0';

         // Trim trailing slashes
         size_t len = strlen(buf);
         if (len > 1) {
             while (len > 0 && buf[len - 1] == '/') {
                 buf[--len] = '\0';
             }
         }

         char *path = buf;
         char parent[PATH_MAX];
        char *last_slash = strrchr(path, '/');
        if (last_slash == path) {
            parent[0] = '/';
            parent[1] = '\0';
        } else if (last_slash) {
            size_t len = last_slash - path;
            strncpy(parent, path, len);
            parent[len] = '\0';
        } else {
            strcpy(parent, ".");
        }

        if (parent[0] == '\0') strcpy(parent, ".");

        struct stat st;
        if (stat(parent, &st) != 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
            any_failure = 1;
            continue;
        }

        if (!S_ISDIR(st.st_mode)) {
            errno = ENOTDIR;
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
            any_failure = 1;
            continue;
        }

        if (stat(path, &st) == 0) {
            errno = EEXIST;
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
            any_failure = 1;
            continue;
        } else if (errno != ENOENT) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
            any_failure = 1;
            continue;
        }

        if (mkdir(path, 0777) != 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
            any_failure = 1;
        }
    }

    return any_failure ? 1 : 0;
}