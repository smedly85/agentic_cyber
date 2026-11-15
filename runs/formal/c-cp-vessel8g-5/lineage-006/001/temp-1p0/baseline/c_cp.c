#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/stat.h>
#include <sys/types.h>

/*
 * copy_path — core filesystem copy operation.
 * Reads the regular file at src (following symlinks) and writes its contents
 * to dst (following dst symlinks to regular files).  Rejects directory sources,
 * dangling destination symlinks, non-regular destinations, and self-copies.
 * Returns 0 on success, 1 on failure (diagnostic on stderr).
 */
static int copy_path(const char *src, const char *dst)
{
    struct stat src_st;
    if (stat(src, &src_st) != 0) {
        fprintf(stderr, "c_cp: %s: %s\n", src, strerror(errno));
        return 1;
    }
    if (!S_ISREG(src_st.st_mode)) {
        fprintf(stderr, "c_cp: %s: not a regular file\n", src);
        return 1;
    }

    struct stat dst_st;
    int dst_exists = (stat(dst, &dst_st) == 0);
    if (!dst_exists) {
        struct stat lst;
        if (lstat(dst, &lst) == 0 && S_ISLNK(lst.st_mode)) {
            fprintf(stderr, "c_cp: %s: dangling symlink\n", dst);
            return 1;
        }
    } else {
        if (!S_ISREG(dst_st.st_mode)) {
            fprintf(stderr, "c_cp: %s: destination not a regular file\n", dst);
            return 1;
        }
        if (src_st.st_dev == dst_st.st_dev && src_st.st_ino == dst_st.st_ino) {
            fprintf(stderr, "c_cp: '%s' and '%s': same file (self-copy)\n", src, dst);
            return 1;
        }
    }

    int src_fd = open(src, O_RDONLY);
    if (src_fd < 0) {
        fprintf(stderr, "c_cp: %s: %s\n", src, strerror(errno));
        return 1;
    }

    int dst_fd;
    if (dst_exists) {
        dst_fd = open(dst, O_WRONLY | O_TRUNC);
    } else {
        dst_fd = open(dst, O_WRONLY | O_CREAT | O_TRUNC,
                      (mode_t)(src_st.st_mode & 0777));
    }
    if (dst_fd < 0) {
        fprintf(stderr, "c_cp: %s: %s\n", dst, strerror(errno));
        close(src_fd);
        return 1;
    }

    char buf[65536];
    for (;;) {
        ssize_t n = read(src_fd, buf, sizeof buf);
        if (n < 0) {
            fprintf(stderr, "c_cp: %s: %s\n", src, strerror(errno));
            close(src_fd);
            close(dst_fd);
            return 1;
        }
        if (n == 0)
            break;
        ssize_t off = 0;
        while (off < n) {
            ssize_t w = write(dst_fd, buf + off, (size_t)(n - off));
            if (w < 0) {
                fprintf(stderr, "c_cp: %s: %s\n", dst, strerror(errno));
                close(src_fd);
                close(dst_fd);
                return 1;
            }
            off += w;
        }
    }

    close(src_fd);
    close(dst_fd);
    return 0;
}

/*
 * basename_of — return pointer to the last path component of a pathname.
 * For "a/b/foo" returns "foo"; for "foo" returns "foo"; for "/foo" returns "foo".
 */
static const char *basename_of(const char *path)
{
    const char *slash = strrchr(path, '/');
    return slash ? slash + 1 : path;
}

int main(int argc, char *argv[])
{
    /* Locate the '--' separator, if any. */
    int dd = -1;
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--") == 0) {
            dd = i;
            break;
        }
    }

    /* Collect operands.
       Before '--': dash-prefixed args (length > 1) are unknown options → error.
       After '--': every argument is a literal operand. */
    int cap = (argc > 1) ? argc - 1 : 1;
    char **ops = malloc((size_t)cap * sizeof *ops);
    if (!ops) {
        fprintf(stderr, "c_cp: out of memory\n");
        return 1;
    }
    int n_ops = 0;

    int lim = (dd >= 0) ? dd : argc;
    for (int i = 1; i < lim; i++) {
        if (argv[i][0] == '-' && argv[i][1] != '\0') {
            fprintf(stderr, "c_cp: unknown option: '%s'\n", argv[i]);
            free(ops);
            return 1;
        }
        ops[n_ops++] = argv[i];
    }
    int after_dd = (dd >= 0) ? dd + 1 : argc;
    for (int i = after_dd; i < argc; i++) {
        ops[n_ops++] = argv[i];
    }

    /* Require at least two operands. */
    if (n_ops < 2) {
        fprintf(stderr, "c_cp: missing required operand\n");
        free(ops);
        return 1;
    }

    /* Multi-source: last operand must be an existing directory (invocation-wide check). */
    int n_src;
    const char *dest;
    if (n_ops == 2) {
        n_src = 1;
        dest = ops[1];
    } else {
        n_src = n_ops - 1;
        dest = ops[n_ops - 1];
        struct stat st;
        if (stat(dest, &st) != 0) {
            fprintf(stderr, "c_cp: %s: %s\n", dest, strerror(errno));
            free(ops);
            return 1;
        }
        if (!S_ISDIR(st.st_mode)) {
            fprintf(stderr, "c_cp: %s: not a directory\n", dest);
            free(ops);
            return 1;
        }
    }

    /* Determine whether single-source dest is a directory (→ use basename). */
    int single_dest_is_dir = 0;
    if (n_ops == 2) {
        struct stat st;
        if (stat(dest, &st) == 0 && S_ISDIR(st.st_mode))
            single_dest_is_dir = 1;
    }

    /* Process each source in operand order; continue on per-source failure. */
    int any_fail = 0;
    for (int i = 0; i < n_src; i++) {
        const char *src = ops[i];
        char *dst = NULL;
        int use_basename = (n_ops > 2) || single_dest_is_dir;

        if (use_basename) {
            const char *base = basename_of(src);
            size_t dlen = strlen(dest);
            size_t blen = strlen(base);
            dst = malloc(dlen + 1 + blen + 1);
            if (!dst) {
                fprintf(stderr, "c_cp: out of memory\n");
                any_fail = 1;
                break;
            }
            memcpy(dst, dest, dlen);
            dst[dlen] = '/';
            memcpy(dst + dlen + 1, base, blen + 1);
        } else {
            size_t dlen = strlen(dest);
            dst = malloc(dlen + 1);
            if (!dst) {
                fprintf(stderr, "c_cp: out of memory\n");
                any_fail = 1;
                break;
            }
            memcpy(dst, dest, dlen + 1);
        }

        if (copy_path(src, dst) != 0)
            any_fail = 1;
        free(dst);
    }

    free(ops);
    return any_fail ? 1 : 0;
}
