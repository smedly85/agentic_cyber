#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
#include <errno.h>

int main(int argc, char **argv) {
    int i;

    int start = 1;
    for (i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--") == 0) {
            start = i + 1;
            break;
        }
        if (argv[i][0] == '-' && strcmp(argv[i], "-") != 0) {
            fprintf(stderr, "mkdir: unrecognized option '%s'\nTry 'mkdir --help' for more information.\n", argv[i]);
            return 1;
        }
    }

    if (argc <= start) {
        fprintf(stderr, "mkdir: missing operand\nTry 'mkdir --help' for more information.\n");
        return 1;
    }

    int error_count = 0;

    for (i = start; i < argc; i++) {
    char *path = strdup(argv[i]);
    if (!path) {
        fprintf(stderr, "mkdir: out of memory\n");
        return 1;
    }
    {
        size_t len = strlen(path);
        while (len > 1 && path[len - 1] == '/') {
            path[--len] = '\0';
        }
    }


        char *parent = ".";
        char *dir_name = path;
        char *last_slash = strrchr(path, '/');

        if (last_slash) {
            *last_slash = '\0';
            parent = path;
            dir_name = last_slash + 1;
        }

        struct stat sb;
        if (stat(parent, &sb) != 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n",
                    argv[i], strerror(errno));
            free(path);
            error_count++;
            continue;
        } else if (!S_ISDIR(sb.st_mode)) {
            errno = ENOTDIR;
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n",
                    argv[i], strerror(errno));
            free(path);
            error_count++;
            continue;
        }

        char *fullpath;
        if (strcmp(parent, ".") == 0) {
            fullpath = strdup(dir_name);
        } else {
            fullpath = malloc(strlen(parent) + strlen(dir_name) + 2);
            if (fullpath) {
                sprintf(fullpath, "%s/%s", parent, dir_name);
            }
        }

        if (!fullpath) {
            free(path);
            fprintf(stderr, "mkdir: out of memory\n");
            return 1;
        }

        if (stat(fullpath, &sb) == 0) {
            errno = EEXIST;
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n",
                    argv[i], strerror(errno));
            free(fullpath);
            free(path);
            error_count++;
            continue;
        } else if (errno != ENOENT) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n",
                    argv[i], strerror(errno));
            free(fullpath);
            free(path);
            error_count++;
            continue;
        }

        if (mkdir(fullpath, 0777) != 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n",
                    argv[i], strerror(errno));
            error_count++;
        }

        free(fullpath);
        free(path);
    }

    return error_count ? 1 : 0;
}