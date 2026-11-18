#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static int create_parents(const char *path)
{
    size_t len = strlen(path);
    if (len == 0) {
        fprintf(stderr, "mkdir: cannot create directory '': %s\n",
                strerror(ENOENT));
        return 1;
    }

    char *buf = malloc(len + 1);
    if (!buf) {
        fprintf(stderr, "mkdir: cannot create directory '%s': %s\n",
                path, strerror(ENOMEM));
        return 1;
    }

    for (size_t i = 1; i <= len; i++) {
        if (i < len && path[i] != '/')
            continue;

        memcpy(buf, path, i);
        buf[i] = '\0';

        /* Skip components that are all slashes (e.g. "/", "//") */
        int all_slashes = 1;
        for (size_t j = 0; j < i; j++) {
            if (path[j] != '/') { all_slashes = 0; break; }
        }
        if (all_slashes)
            continue;

        struct stat st;
        if (lstat(buf, &st) == 0) {
            if (S_ISDIR(st.st_mode))
                continue;
            if (S_ISLNK(st.st_mode)) {
                struct stat st2;
                if (stat(buf, &st2) == 0 && S_ISDIR(st2.st_mode))
                    continue;
            }
            /* Exists but is not a directory */
            errno = (i == len) ? EEXIST : ENOTDIR;
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n",
                    path, strerror(errno));
            free(buf);
            return 1;
        }

        if (errno != ENOENT) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n",
                    path, strerror(errno));
            free(buf);
            return 1;
        }

        if (mkdir(buf, 0777) != 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n",
                    path, strerror(errno));
            free(buf);
            return 1;
        }

        /* Intermediate directories: ensure owner has write + execute */
        if (i < len) {
            if (lstat(buf, &st) == 0) {
                mode_t m = st.st_mode;
                if (!(m & (S_IWUSR | S_IXUSR)))
                    chmod(buf, m | S_IWUSR | S_IXUSR);
            }
        }
    }

    free(buf);
    return 0;
}

int main(int argc, char *argv[])
{
    /* Pass 1: parse options (no filesystem mutation) */
    int parents = 0;
    int opt_done = 0;
    int has_operand = 0;

    for (int i = 1; i < argc; i++) {
        if (opt_done) {
            has_operand = 1;
            continue;
        }
        if (strcmp(argv[i], "--") == 0) {
            opt_done = 1;
            continue;
        }
        if (strcmp(argv[i], "-p") == 0 || strcmp(argv[i], "--parents") == 0) {
            parents = 1;
            continue;
        }
        if (argv[i][0] == '-' && argv[i][1] != '\0') {
            fprintf(stderr, "mkdir: unrecognized option '%s'\n", argv[i]);
            fprintf(stderr, "Try 'mkdir --help' for more information.\n");
            return 1;
        }
        has_operand = 1;
    }

    if (!has_operand) {
        fprintf(stderr, "mkdir: missing operand\n");
        fprintf(stderr, "Try 'mkdir --help' for more information.\n");
        return 1;
    }

    /* Pass 2: create directories in order, continuing after errors */
    int all_ok = 1;
    opt_done = 0;

    for (int i = 1; i < argc; i++) {
        if (!opt_done) {
            if (strcmp(argv[i], "--") == 0) { opt_done = 1; continue; }
            if (strcmp(argv[i], "-p") == 0 || strcmp(argv[i], "--parents") == 0)
                continue;
            if (argv[i][0] == '-' && argv[i][1] != '\0')
                continue;
        }

        int rc;
        if (parents) {
            rc = create_parents(argv[i]);
        } else {
            if (mkdir(argv[i], 0777) != 0) {
                fprintf(stderr, "mkdir: cannot create directory '%s': %s\n",
                        argv[i], strerror(errno));
                rc = 1;
            } else {
                rc = 0;
            }
        }
        if (rc != 0)
            all_ok = 0;
    }

    return all_ok ? 0 : 1;
}
