#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

int main(int argc, char *argv[]) {
    int i = 1;
    while (i < argc) {
        if (argv[i][0] != '-') break;
        if (argv[i][1] == '\0') break;
        if (argv[i][1] == '-' && argv[i][2] == '\0') { i++; break; }
        fprintf(stderr, "mkdir: unrecognized option '%s'\nTry 'mkdir --help' for more information.\n", argv[i]);
        exit(1);
    }

    if (i >= argc) {
        fprintf(stderr, "mkdir: missing operand\nTry 'mkdir --help' for more information.\n");
        exit(1);
    }

    int all_success = 1;
    for (int j = i; j < argc; j++) {
        char *original_path = argv[j];
        char *path = strdup(original_path);
        if (!path) { fprintf(stderr, "mkdir: out of memory\n"); exit(1); }
        size_t path_len = strlen(path);
        if (path_len > 1) { while (path_len > 0 && path[path_len-1] == '/') { path[path_len-1] = '\0'; path_len--; } }
        char *last_slash = strrchr(path, '/');
        char *dir; int dir_allocated = 0; char *base;

        if (last_slash == NULL) {
            dir = "."; base = path;
        } else {
            if (last_slash == path) dir = "/";
            else {
                dir = strndup(path, last_slash - path);
                if (!dir) { fprintf(stderr, "new_mkdir: out of memory\n"); exit(1); }
                dir_allocated = 1;
            }
            base = last_slash + 1;
        }

    
        if (!base[0]) {
            fprintf(stderr, "mkdir: cannot create directory '%s': invalid name\n", original_path);
            all_success = 0; if (dir_allocated) free(dir); continue;
        }

        struct stat st;
        if (stat(dir, &st) != 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", original_path, strerror(errno));
            all_success = 0; if (dir_allocated) free(dir); continue;
        }
        if (!S_ISDIR(st.st_mode)) {
            fprintf(stderr, "mkdir: cannot create directory '%s': Not a directory\n", original_path);
            all_success = 0; if (dir_allocated) free(dir); continue;
        }

        char *full_path;
        if (!strcmp(dir, "/")) {
            full_path = malloc(strlen(base) + 2);
            if (!full_path) { fprintf(stderr, "new_mkdir: out of memory\n"); exit(1); }
            sprintf(full_path, "/%s", base);
        } else {
            full_path = malloc(strlen(dir) + strlen(base) + 2);
            if (!full_path) { fprintf(stderr, "new_mkdir: out of memory\n"); exit(1); }
            sprintf(full_path, "%s/%s", dir, base);
        }

        if (stat(full_path, &st) == 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': File exists\n", original_path);
            all_success = 0; free(full_path); if (dir_allocated) free(dir); continue;
        }

        if (mkdir(full_path, 0777) != 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", original_path, strerror(errno));
            all_success = 0;
        }

        free(full_path);
        if (dir_allocated) free(dir);
    }
    return all_success ? 0 : 1;
}