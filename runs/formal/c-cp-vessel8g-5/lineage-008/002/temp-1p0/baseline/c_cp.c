#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <errno.h>

static const char *get_basename(const char *path)
{
    const char *slash = strrchr(path, '/');
    return slash ? slash + 1 : path;
}

static char *join_path(const char *dir, const char *name)
{
    size_t dlen = strlen(dir);
    size_t nlen = strlen(name);
    int need_slash = (dlen == 0 || dir[dlen - 1] != '/');
    size_t total = dlen + (need_slash ? 1 : 0) + nlen + 1;
    char *result = malloc(total);
    if (!result)
        return NULL;
    memcpy(result, dir, dlen);
    size_t pos = dlen;
    if (need_slash)
        result[pos++] = '/';
    memcpy(result + pos, name, nlen + 1);
    return result;
}

static int copy_path(const char *src, const char *dst, int force)
{
    struct stat src_stat;

    if (stat(src, &src_stat) != 0) {
        fprintf(stderr, "c_cp: cannot read '%s': %s\n", src, strerror(errno));
        return -1;
    }
    if (!S_ISREG(src_stat.st_mode)) {
        if (S_ISDIR(src_stat.st_mode))
            fprintf(stderr, "c_cp: cannot copy directory '%s'\n", src);
        else
            fprintf(stderr, "c_cp: cannot copy '%s': not a regular file\n", src);
        return -1;
    }

    struct stat dst_stat;
    int dst_exists = 0;

    {
        struct stat dst_ls;
        if (lstat(dst, &dst_ls) == 0) {
            dst_exists = 1;
            if (S_ISREG(dst_ls.st_mode)) {
                dst_stat = dst_ls;
            } else if (S_ISLNK(dst_ls.st_mode)) {
                if (stat(dst, &dst_stat) != 0) {
                    fprintf(stderr, "c_cp: destination '%s' is a dangling symlink\n", dst);
                    return -1;
                }
                if (!S_ISREG(dst_stat.st_mode)) {
                    fprintf(stderr, "c_cp: destination '%s' is not a regular file\n", dst);
                    return -1;
                }
            } else if (S_ISDIR(dst_ls.st_mode)) {
                fprintf(stderr, "c_cp: destination '%s' is a directory\n", dst);
                return -1;
            } else {
                fprintf(stderr, "c_cp: destination '%s' is not a regular file\n", dst);
                return -1;
            }
        } else if (errno != ENOENT) {
            fprintf(stderr, "c_cp: cannot access '%s': %s\n", dst, strerror(errno));
            return -1;
        }
    }

    if (dst_exists && src_stat.st_dev == dst_stat.st_dev &&
        src_stat.st_ino == dst_stat.st_ino) {
        fprintf(stderr, "c_cp: '%s' and '%s' are the same file\n", src, dst);
        return -1;
    }

    int src_fd = open(src, O_RDONLY);
    if (src_fd < 0) {
        fprintf(stderr, "c_cp: cannot read '%s': %s\n", src, strerror(errno));
        return -1;
    }

    int dst_fd;
    if (dst_exists) {
        dst_fd = open(dst, O_WRONLY | O_TRUNC);
        if (dst_fd < 0 && force) {
            int save_errno = errno;
            if (unlink(dst) == 0)
                dst_fd = open(dst, O_WRONLY | O_CREAT | O_TRUNC,
                              src_stat.st_mode & 0777);
            if (dst_fd < 0)
                errno = save_errno;
        }
    } else {
        dst_fd = open(dst, O_WRONLY | O_CREAT | O_TRUNC, src_stat.st_mode & 0777);
    }

    if (dst_fd < 0) {
        fprintf(stderr, "c_cp: cannot write '%s': %s\n", dst, strerror(errno));
        close(src_fd);
        return -1;
    }

    enum { BUF_SIZE = 65536 };
    char buf[BUF_SIZE];
    ssize_t n;

    while ((n = read(src_fd, buf, BUF_SIZE)) > 0) {
        ssize_t offset = 0;
        while (offset < n) {
            ssize_t w = write(dst_fd, buf + offset, (size_t)(n - offset));
            if (w < 0) {
                if (errno == EINTR)
                    continue;
                fprintf(stderr, "c_cp: write error '%s': %s\n", dst, strerror(errno));
                close(src_fd);
                close(dst_fd);
                return -1;
            }
            offset += w;
        }
    }

    if (n < 0) {
        fprintf(stderr, "c_cp: read error '%s': %s\n", src, strerror(errno));
        close(src_fd);
        close(dst_fd);
        return -1;
    }

    close(src_fd);
    close(dst_fd);
    return 0;
}

int main(int argc, char *argv[])
{
    int end_of_opts = 0;
    int n_operands = 0;
    int max_possible = (argc > 1) ? argc - 1 : 0;
    int *operand_idx = NULL;
    int force = 0;

    if (max_possible > 0) {
        operand_idx = malloc(sizeof(int) * (size_t)max_possible);
        if (!operand_idx) {
            fprintf(stderr, "c_cp: out of memory\n");
            return 1;
        }
    }

    for (int i = 1; i < argc; i++) {
        if (!end_of_opts) {
            if (strcmp(argv[i], "--") == 0) {
                end_of_opts = 1;
                continue;
            }
            if (argv[i][0] == '-' && argv[i][1] != '\0') {
                if (strcmp(argv[i], "-f") == 0 || strcmp(argv[i], "--force") == 0) {
                    force = 1;
                    continue;
                }
                fprintf(stderr, "c_cp: unknown option '%s'\n", argv[i]);
                free(operand_idx);
                return 1;
            }
        }
        operand_idx[n_operands++] = i;
    }

    if (n_operands < 2) {
        fprintf(stderr, "c_cp: missing operand\n");
        free(operand_idx);
        return 1;
    }

    const char *dest_dir = NULL;
    if (n_operands > 2) {
        const char *last = argv[operand_idx[n_operands - 1]];
        struct stat st;
        if (stat(last, &st) != 0 || !S_ISDIR(st.st_mode)) {
            fprintf(stderr, "c_cp: '%s' is not a directory\n", last);
            free(operand_idx);
            return 1;
        }
        dest_dir = last;
    }

    int any_failed = 0;
    int n_sources = n_operands - 1;

    for (int i = 0; i < n_sources; i++) {
        const char *src = argv[operand_idx[i]];
        char *dst = NULL;

        if (dest_dir) {
            dst = join_path(dest_dir, get_basename(src));
        } else {
            const char *dest = argv[operand_idx[1]];
            struct stat st;
            if (stat(dest, &st) == 0 && S_ISDIR(st.st_mode)) {
                dst = join_path(dest, get_basename(src));
            } else {
                dst = strdup(dest);
            }
        }

        if (!dst) {
            fprintf(stderr, "c_cp: out of memory\n");
            any_failed = 1;
            continue;
        }

        if (copy_path(src, dst, force) != 0)
            any_failed = 1;

        free(dst);
    }

    free(operand_idx);
    return any_failed ? 1 : 0;
}
