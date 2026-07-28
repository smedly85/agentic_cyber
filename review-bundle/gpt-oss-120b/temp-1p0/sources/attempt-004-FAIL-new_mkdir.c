#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/stat.h>
#include <unistd.h>

static void emit_error(const char *msg) {
    fprintf(stderr, "%s\n", msg);
}

int main(int argc, char *argv[]) {
    int exit_status = 0;
    int end_of_options = 0;
    int any_operand = 0;
    for (int i = 1; i < argc; ++i) {
        const char *arg = argv[i];
        if (!end_of_options && strcmp(arg, "--") == 0) {
            end_of_options = 1;
            continue;
        }
        if (!end_of_options && arg[0] == '-' && !(strcmp(arg, "-") == 0)) {
            emit_error("new_mkdir: unrecognized option");
            return 1;
        }
        any_operand = 1;
        const char *path = arg;
        const char *slash = strrchr(path, '/');
                char *parent_path = NULL;
        if (slash) {
            size_t len = slash - path;
            if (len == 0) {
                parent_path = "/"; // root
            } else {
                char *tmp = strndup(path, len);
                if (!tmp) { emit_error("new_mkdir: memory allocation failed"); return 1; }
                parent_path = tmp;
            }
        } else {
            parent_path = ".";
        }
        struct stat sb;
        if (stat(parent_path, &sb) != 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
            exit_status = 1;
        } else if (!S_ISDIR(sb.st_mode)) {
            fprintf(stderr, "mkdir: cannot create directory '%s': Not a directory\n", path);
            exit_status = 1;
        } else {
            struct stat sb2;
            if (stat(path, &sb2) == 0) {
                fprintf(stderr, "mkdir: cannot create directory '%s': File exists\n", path);
                exit_status = 1;
            } else {
                if (mkdir(path, 0777) != 0) {
                    fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(errno));
                    exit_status = 1;
                }
            }
        }
        if (slash && parent_path != "." && parent_path != "/") {
            free((void *)parent_path);
        }
    }
    if (!any_operand) { emit_error("missing operand"); return 1; }
    return exit_status;
}
