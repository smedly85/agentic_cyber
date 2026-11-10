#define _XOPEN_SOURCE 700
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>
#include <ctype.h>
#include <dirent.h>

#define COPY_BUF (256 * 1024)

static int copy_path(const char *src, const char *dst, int force, int interactive)
{
    struct stat src_st;
    struct stat dst_st;
    int src_fd, dst_fd;
    char buf[COPY_BUF];
    ssize_t n;
    int dst_is_new;
    int rc = -1;

    if (stat(src, &src_st) != 0) {
        fprintf(stderr, "cp: %s: %s\n", src, strerror(errno));
        return -1;
    }
    if (!S_ISREG(src_st.st_mode)) {
        fprintf(stderr, "cp: %s: not a regular file\n", src);
        return -1;
    }

    int dst_exists = (stat(dst, &dst_st) == 0);
    if (dst_exists) {
        if (!S_ISREG(dst_st.st_mode)) {
            fprintf(stderr, "cp: %s: destination is not a regular file\n", dst);
            return -1;
        }
        if (src_st.st_dev == dst_st.st_dev &&
            src_st.st_ino == dst_st.st_ino) {
            fprintf(stderr, "cp: '%s' and '%s' are the same file\n", src, dst);
            return -1;
        }
        dst_is_new = 0;
    } else {
        struct stat link_st;
        if (lstat(dst, &link_st) == 0 && S_ISLNK(link_st.st_mode)) {
            if (force) {
                if (unlink(dst) != 0) {
                    fprintf(stderr, "cp: %s: %s\n", dst, strerror(errno));
                    return -1;
                }
            } else {
                fprintf(stderr, "cp: %s: destination is a dangling symlink\n", dst);
                return -1;
            }
        }
        dst_is_new = 1;
    }

    if (dst_exists && interactive) {
        fprintf(stderr, "cp: overwrite '%s', continue? ", dst);
        fflush(stderr);
        char line[256];
        if (fgets(line, sizeof(line), stdin) == NULL)
            return -2;
        if (line[0] != 'y' && line[0] != 'Y')
            return -2;
    }

    src_fd = open(src, O_RDONLY);
    if (src_fd < 0) {
        fprintf(stderr, "cp: %s: %s\n", src, strerror(errno));
        return -1;
    }

    int flags = O_WRONLY | O_TRUNC;
    if (dst_is_new)
        flags |= O_CREAT;
    mode_t mode = dst_is_new ? (mode_t)(src_st.st_mode & 0777) : 0;
    dst_fd = open(dst, flags, mode);
    if (dst_fd < 0 && force && !dst_is_new) {
        struct stat dest_st;
        if (lstat(dst, &dest_st) == 0 && !S_ISDIR(dest_st.st_mode)) {
            if (unlink(dst) == 0) {
                dst_fd = open(dst, O_WRONLY | O_CREAT, (mode_t)(src_st.st_mode & 0777));
            }
        }
    }
    if (dst_fd < 0) {
        fprintf(stderr, "cp: %s: %s\n", dst, strerror(errno));
        close(src_fd);
        return -1;
    }

    for (;;) {
        n = read(src_fd, buf, sizeof(buf));
        if (n < 0) {
            fprintf(stderr, "cp: %s: %s\n", src, strerror(errno));
            goto fail;
        }
        if (n == 0)
            break;
        ssize_t off = 0;
        while (off < n) {
            ssize_t w = write(dst_fd, buf + off, (size_t)(n - off));
            if (w < 0) {
                fprintf(stderr, "cp: %s: %s\n", dst, strerror(errno));
                goto fail;
            }
            off += w;
        }
    }

    close(src_fd);
    close(dst_fd);
    return 0;

fail:
    close(src_fd);
    close(dst_fd);
    (void)rc;
    return -1;
}

static const char *path_basename(const char *path)
{
    const char *slash = strrchr(path, '/');
    return slash ? slash + 1 : path;
}

static int build_path(char *buf, size_t size, const char *dir, const char *name)
{
    int n = snprintf(buf, size, "%s/%s", dir, name);
    return (n < 0 || (size_t)n >= size) ? -1 : 0;
}

static int dst_inside_src(const char *src_dir, const char *effective_dst)
{
    char src_real[PATH_MAX];
    if (realpath(src_dir, src_real) == NULL)
        return 0;
    size_t srclen = strlen(src_real);

    char dst_real[PATH_MAX];
    if (realpath(effective_dst, dst_real) != NULL) {
        if (strcmp(src_real, dst_real) == 0) return 1;
        if (strncmp(src_real, dst_real, srclen) == 0 && dst_real[srclen] == '/')
            return 1;
        return 0;
    }

    char work[PATH_MAX];
    snprintf(work, sizeof(work), "%s", effective_dst);

    char existing_prefix[PATH_MAX] = "";
    for (char *p = work + 1; *p; p++) {
        if (*p == '/') {
            *p = '\0';
            if (access(work, F_OK) == 0)
                snprintf(existing_prefix, sizeof(existing_prefix), "%s", work);
            *p = '/';
        }
    }

    if (existing_prefix[0] == '\0')
        return 0;

    char prefix_real[PATH_MAX];
    if (realpath(existing_prefix, prefix_real) == NULL)
        return 0;

    size_t plen = strlen(existing_prefix);
    const char *remaining = effective_dst + plen;
    char combined[PATH_MAX];
    int n = snprintf(combined, sizeof(combined), "%s%s", prefix_real, remaining);
    if (n < 0 || (size_t)n >= sizeof(combined))
        return 0;

    if (strcmp(src_real, combined) == 0) return 1;
    if (strncmp(src_real, combined, srclen) == 0 && combined[srclen] == '/')
        return 1;
    return 0;
}

static int copy_tree(const char *src, const char *dst, int force, int interactive);

static int copy_entry(const char *src, const char *dst, int force, int interactive)
{
    struct stat st;
    if (lstat(src, &st) != 0) {
        fprintf(stderr, "cp: %s: %s\n", src, strerror(errno));
        return -1;
    }

    if (S_ISLNK(st.st_mode)) {
        char target[PATH_MAX];
        ssize_t len = readlink(src, target, sizeof(target) - 1);
        if (len < 0) {
            fprintf(stderr, "cp: %s: %s\n", src, strerror(errno));
            return -1;
        }
        target[len] = '\0';

        struct stat dst_st;
        if (lstat(dst, &dst_st) == 0) {
            if (S_ISDIR(dst_st.st_mode)) {
                fprintf(stderr, "cp: %s: destination is a directory\n", dst);
                return -1;
            }
            if (force) {
                if (unlink(dst) != 0) {
                    fprintf(stderr, "cp: %s: %s\n", dst, strerror(errno));
                    return -1;
                }
            } else if (interactive) {
                fprintf(stderr, "cp: overwrite '%s', continue? ", dst);
                fflush(stderr);
                char line[256];
                if (fgets(line, sizeof(line), stdin) == NULL)
                    return -1;
                if (line[0] != 'y' && line[0] != 'Y')
                    return -1;
                if (unlink(dst) != 0) {
                    fprintf(stderr, "cp: %s: %s\n", dst, strerror(errno));
                    return -1;
                }
            } else {
                fprintf(stderr, "cp: %s: destination exists\n", dst);
                return -1;
            }
        }

        if (symlink(target, dst) != 0) {
            fprintf(stderr, "cp: %s: %s\n", dst, strerror(errno));
            return -1;
        }
        return 0;
    }

    if (S_ISDIR(st.st_mode))
        return copy_tree(src, dst, force, interactive);

    if (S_ISREG(st.st_mode))
        return copy_path(src, dst, force, interactive);

    fprintf(stderr, "cp: %s: unsupported file type\n", src);
    return -1;
}

static int copy_tree(const char *src, const char *dst, int force, int interactive)
{
    struct stat src_st;
    if (stat(src, &src_st) != 0) {
        fprintf(stderr, "cp: %s: %s\n", src, strerror(errno));
        return -1;
    }
    if (!S_ISDIR(src_st.st_mode)) {
        fprintf(stderr, "cp: %s: not a directory\n", src);
        return -1;
    }

    if (dst_inside_src(src, dst)) {
        fprintf(stderr, "cp: %s: cannot copy a directory into itself\n", src);
        return -1;
    }

    struct stat dst_st;
    if (lstat(dst, &dst_st) == 0) {
        if (!S_ISDIR(dst_st.st_mode)) {
            fprintf(stderr, "cp: %s: destination is not a directory\n", dst);
            return -1;
        }
    } else {
        if (mkdir(dst, src_st.st_mode & 0777) != 0) {
            fprintf(stderr, "cp: %s: %s\n", dst, strerror(errno));
            return -1;
        }
    }

    DIR *dir = opendir(src);
    if (!dir) {
        fprintf(stderr, "cp: %s: %s\n", src, strerror(errno));
        return -1;
    }

    int any_fail = 0;
    struct dirent *entry;
    while ((entry = readdir(dir)) != NULL) {
        if (strcmp(entry->d_name, ".") == 0 || strcmp(entry->d_name, "..") == 0)
            continue;

        char src_path[PATH_MAX], dst_path[PATH_MAX];
        int n1 = snprintf(src_path, sizeof(src_path), "%s/%s", src, entry->d_name);
        int n2 = snprintf(dst_path, sizeof(dst_path), "%s/%s", dst, entry->d_name);
        if (n1 < 0 || (size_t)n1 >= sizeof(src_path) ||
            n2 < 0 || (size_t)n2 >= sizeof(dst_path)) {
            fprintf(stderr, "cp: %s: path too long\n", entry->d_name);
            any_fail = 1;
            continue;
        }

        if (copy_entry(src_path, dst_path, force, interactive) != 0)
            any_fail = 1;
    }
    closedir(dir);

    return any_fail ? -1 : 0;
}

int main(int argc, char *argv[])
{
    int saw_dd = 0;
    int force = 0;
    int interactive = 0;
    int recursive = 0;
    char **op = NULL;
    int n_op = 0, cap = 0;

    for (int i = 1; i < argc; i++) {
        if (!saw_dd) {
            if (strcmp(argv[i], "--") == 0) {
                saw_dd = 1;
                continue;
            }
            if (argv[i][0] == '-' && argv[i][1] != '\0') {
                if (strcmp(argv[i], "-f") == 0 || strcmp(argv[i], "--force") == 0) {
                    force = 1;
                    continue;
                }
                if (strcmp(argv[i], "-i") == 0 || strcmp(argv[i], "--interactive") == 0) {
                    interactive = 1;
                    continue;
                }
                if (strcmp(argv[i], "-r") == 0 || strcmp(argv[i], "--recursive") == 0) {
                    recursive = 1;
                    continue;
                }
                fprintf(stderr, "cp: unknown option: %s\n", argv[i]);
                return 1;
            }
        }
        if (n_op == cap) {
            cap = cap ? cap * 2 : 8;
            char **tmp = realloc(op, (size_t)cap * sizeof(*tmp));
            if (!tmp) {
                fprintf(stderr, "cp: out of memory\n");
                free(op);
                return 1;
            }
            op = tmp;
        }
        op[n_op++] = argv[i];
    }

    if (n_op < 2) {
        fprintf(stderr, "cp: missing operand\n");
        free(op);
        return 1;
    }

    int multi = (n_op > 2);
    const char *last = op[n_op - 1];

    if (multi) {
        struct stat st;
        if (stat(last, &st) != 0 || !S_ISDIR(st.st_mode)) {
            fprintf(stderr, "cp: %s: target is not a directory\n", last);
            free(op);
            return 1;
        }
    }

    int n_src = multi ? (n_op - 1) : 1;
    int any_fail = 0;

    for (int i = 0; i < n_src; i++) {
        const char *src = op[i];
        char dst_buf[PATH_MAX];
        const char *dst;

        if (multi) {
            if (build_path(dst_buf, sizeof(dst_buf), last, path_basename(src)) != 0) {
                fprintf(stderr, "cp: %s: path too long\n", src);
                any_fail = 1;
                continue;
            }
            dst = dst_buf;
        } else {
            dst = op[1];
            struct stat st;
            if (stat(dst, &st) == 0 && S_ISDIR(st.st_mode)) {
                if (build_path(dst_buf, sizeof(dst_buf), dst, path_basename(src)) != 0) {
                    fprintf(stderr, "cp: %s: path too long\n", src);
                    any_fail = 1;
                    continue;
                }
                dst = dst_buf;
            }
        }

        if (recursive) {
            struct stat st;
            if (lstat(src, &st) == 0) {
                if (S_ISDIR(st.st_mode)) {
                    if (copy_tree(src, dst, force, interactive) != 0)
                        any_fail = 1;
                } else {
                    if (copy_entry(src, dst, force, interactive) != 0)
                        any_fail = 1;
                }
            } else {
                fprintf(stderr, "cp: %s: %s\n", src, strerror(errno));
                any_fail = 1;
            }
        } else {
            if (copy_path(src, dst, force, interactive) != 0)
                any_fail = 1;
        }
    }

    free(op);
    return any_fail ? 1 : 0;
}
