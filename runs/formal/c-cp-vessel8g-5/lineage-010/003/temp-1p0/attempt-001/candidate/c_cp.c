#ifndef _POSIX_C_SOURCE
#define _POSIX_C_SOURCE 200809L
#endif
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static const char *get_basename(const char *path) {
    const char *slash = strrchr(path, '/');
    return slash ? slash + 1 : path;
}

static int copy_path(const char *src, const char *dst, int force, int interactive) {
    struct stat st_src;

    if (stat(src, &st_src) != 0) {
        fprintf(stderr, "c_cp: %s: %s\n", src, strerror(errno));
        return 1;
    }
    if (!S_ISREG(st_src.st_mode)) {
        fprintf(stderr, "c_cp: %s: not a regular file\n", src);
        return 1;
    }

    int dst_existed = 0;
    struct stat st_dst;

    struct stat st_link;
    int dst_is_link = (lstat(dst, &st_link) == 0 && S_ISLNK(st_link.st_mode));

    if (stat(dst, &st_dst) == 0) {
        dst_existed = 1;
        if (S_ISDIR(st_dst.st_mode)) {
            fprintf(stderr, "c_cp: %s: destination is a directory\n", dst);
            return 1;
        }
        if (!S_ISREG(st_dst.st_mode)) {
            fprintf(stderr, "c_cp: %s: destination is not a regular file\n", dst);
            return 1;
        }
        if (st_src.st_dev == st_dst.st_dev && st_src.st_ino == st_dst.st_ino) {
            fprintf(stderr, "c_cp: '%s' and '%s' are the same file\n", src, dst);
            return 1;
        }
    } else if (dst_is_link) {
        if (!force) {
            fprintf(stderr, "c_cp: %s: dangling symbolic link\n", dst);
            return 1;
        }
    }

    if (interactive && dst_existed) {
        fprintf(stderr, "c_cp: overwrite %s? ", dst);
        fflush(stderr);
        int first = getc(stdin);
        int c;
        while ((c = getc(stdin)) != EOF && c != '\n') {}
        if (first != 'y' && first != 'Y') {
            return 1;
        }
    }

    int fd_src = open(src, O_RDONLY);
    if (fd_src < 0) {
        fprintf(stderr, "c_cp: %s: %s\n", src, strerror(errno));
        return 1;
    }

    int fd_dst;
    if (dst_existed) {
        fd_dst = open(dst, O_WRONLY | O_TRUNC);
        if (fd_dst < 0) {
            int saved_errno = errno;
            if (force && unlink(dst) == 0) {
                fd_dst = open(dst, O_WRONLY | O_CREAT | O_TRUNC, st_src.st_mode & 0777);
            }
            if (fd_dst < 0) {
                errno = saved_errno;
                fprintf(stderr, "c_cp: %s: %s\n", dst, strerror(errno));
                close(fd_src);
                return 1;
            }
        }
    } else if (dst_is_link) {
        if (unlink(dst) != 0) {
            fprintf(stderr, "c_cp: %s: %s\n", dst, strerror(errno));
            close(fd_src);
            return 1;
        }
        fd_dst = open(dst, O_WRONLY | O_CREAT | O_TRUNC, st_src.st_mode & 0777);
        if (fd_dst < 0) {
            fprintf(stderr, "c_cp: %s: %s\n", dst, strerror(errno));
            close(fd_src);
            return 1;
        }
    } else {
        fd_dst = open(dst, O_WRONLY | O_CREAT | O_TRUNC, st_src.st_mode & 0777);
        if (fd_dst < 0) {
            fprintf(stderr, "c_cp: %s: %s\n", dst, strerror(errno));
            close(fd_src);
            return 1;
        }
    }

    enum { BUFSZ = 65536 };
    char buf[BUFSZ];
    for (;;) {
        ssize_t n = read(fd_src, buf, BUFSZ);
        if (n < 0) {
            if (errno == EINTR) continue;
            fprintf(stderr, "c_cp: %s: %s\n", src, strerror(errno));
            close(fd_src);
            close(fd_dst);
            return 1;
        }
        if (n == 0) break;
        ssize_t off = 0;
        while (off < n) {
            ssize_t w = write(fd_dst, buf + off, (size_t)(n - off));
            if (w < 0) {
                if (errno == EINTR) continue;
                fprintf(stderr, "c_cp: %s: %s\n", dst, strerror(errno));
                close(fd_src);
                close(fd_dst);
                return 1;
            }
            off += w;
        }
    }

    close(fd_src);
    if (close(fd_dst) != 0) {
        fprintf(stderr, "c_cp: %s: %s\n", dst, strerror(errno));
        return 1;
    }
    return 0;
}

static int same_or_descendant(const char *ref, const char *path) {
    struct stat st_ref, st_cur;
    if (stat(ref, &st_ref) != 0) return 0;

    size_t len = strlen(path);
    if (len == 0 || len >= 4096) return 0;

    char buf[4096];
    memcpy(buf, path, len + 1);

    for (;;) {
        if (stat(buf, &st_cur) == 0 &&
            st_cur.st_dev == st_ref.st_dev && st_cur.st_ino == st_ref.st_ino)
            return 1;
        char *slash = strrchr(buf, '/');
        if (!slash) return 0;
        *slash = '\0';
        if (buf[0] == '\0') {
            if (stat("/", &st_cur) == 0 &&
                st_cur.st_dev == st_ref.st_dev && st_cur.st_ino == st_ref.st_ino)
                return 1;
            return 0;
        }
    }
}

static int copy_recursive(const char *src, const char *dst, int force, int interactive) {
    struct stat lst;
    if (lstat(src, &lst) != 0) {
        fprintf(stderr, "c_cp: %s: %s\n", src, strerror(errno));
        return 1;
    }

    /* Symlink: recreate with identical target bytes; never traverse. */
    if (S_ISLNK(lst.st_mode)) {
        char target[4096];
        ssize_t len = readlink(src, target, sizeof(target) - 1);
        if (len < 0) {
            fprintf(stderr, "c_cp: %s: %s\n", src, strerror(errno));
            return 1;
        }
        target[len] = '\0';
        struct stat st_dst;
        if (lstat(dst, &st_dst) == 0) {
            if (unlink(dst) != 0) {
                fprintf(stderr, "c_cp: %s: %s\n", dst, strerror(errno));
                return 1;
            }
        }
        if (symlink(target, dst) != 0) {
            fprintf(stderr, "c_cp: %s: %s\n", dst, strerror(errno));
            return 1;
        }
        return 0;
    }

    struct stat st;
    if (stat(src, &st) != 0) {
        fprintf(stderr, "c_cp: %s: %s\n", src, strerror(errno));
        return 1;
    }

    /* Regular file: delegate to copy_path (handles force/interactive). */
    if (S_ISREG(st.st_mode)) {
        return copy_path(src, dst, force, interactive);
    }

    if (!S_ISDIR(st.st_mode)) {
        fprintf(stderr, "c_cp: %s: unsupported file type\n", src);
        return 1;
    }

    /* --- Directory: self-copy guard, create dst, recurse into entries --- */

    struct stat st_dst;
    if (lstat(dst, &st_dst) == 0) {
        if (!S_ISDIR(st_dst.st_mode)) {
            fprintf(stderr, "c_cp: %s: not a directory\n", dst);
            return 1;
        }
        if (same_or_descendant(src, dst)) {
            fprintf(stderr, "c_cp: cannot copy '%s' into itself\n", src);
            return 1;
        }
    } else {
        char parent[4096];
        const char *last_slash = NULL;
        for (const char *c = dst; *c; c++) {
            if (*c == '/') last_slash = c;
        }
        int do_check = 0;
        if (last_slash == NULL) {
            strcpy(parent, ".");
            do_check = 1;
        } else if (last_slash == dst) {
            strcpy(parent, "/");
            do_check = 1;
        } else {
            size_t plen = (size_t)(last_slash - dst);
            if (plen < sizeof(parent)) {
                memcpy(parent, dst, plen);
                parent[plen] = '\0';
                do_check = 1;
            }
        }
        if (do_check && same_or_descendant(src, parent)) {
            fprintf(stderr, "c_cp: cannot copy '%s' into itself\n", src);
            return 1;
        }
        if (mkdir(dst, st.st_mode & 0777) != 0) {
            fprintf(stderr, "c_cp: %s: %s\n", dst, strerror(errno));
            return 1;
        }
    }

    /* Recurse into directory entries */
    DIR *dir = opendir(src);
    if (!dir) {
        fprintf(stderr, "c_cp: %s: %s\n", src, strerror(errno));
        return 1;
    }

    int any_failure = 0;
    struct dirent *entry;
    while ((entry = readdir(dir)) != NULL) {
        if (strcmp(entry->d_name, ".") == 0 || strcmp(entry->d_name, "..") == 0)
            continue;

        size_t src_len = strlen(src);
        size_t dst_len = strlen(dst);
        size_t name_len = strlen(entry->d_name);
        int src_slash = (src_len > 0 && src[src_len - 1] == '/') ? 0 : 1;
        int dst_slash = (dst_len > 0 && dst[dst_len - 1] == '/') ? 0 : 1;

        if (src_len + (size_t)src_slash + name_len + 1 > 4096 ||
            dst_len + (size_t)dst_slash + name_len + 1 > 4096) {
            fprintf(stderr, "c_cp: path too long\n");
            any_failure = 1;
            continue;
        }

        char src_child[4096];
        char dst_child[4096];
        memcpy(src_child, src, src_len);
        if (src_slash) src_child[src_len] = '/';
        memcpy(src_child + src_len + (size_t)src_slash, entry->d_name, name_len + 1);

        memcpy(dst_child, dst, dst_len);
        if (dst_slash) dst_child[dst_len] = '/';
        memcpy(dst_child + dst_len + (size_t)dst_slash, entry->d_name, name_len + 1);

        if (copy_recursive(src_child, dst_child, force, interactive) != 0) {
            any_failure = 1;
        }
    }
    closedir(dir);
    return any_failure ? 1 : 0;
}

int main(int argc, char *argv[]) {
    const char *operands[argc > 1 ? argc - 1 : 1];
    int n_op = 0;
    int ddash = 0;
    int force = 0;
    int interactive = 0;
    int recursive = 0;

    for (int i = 1; i < argc; i++) {
        if (!ddash && strcmp(argv[i], "--") == 0) {
            ddash = 1;
            continue;
        }
        if (!ddash && argv[i][0] == '-' && argv[i][1] != '\0') {
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
            fprintf(stderr, "c_cp: unknown option: %s\n", argv[i]);
            return 1;
        }
        operands[n_op++] = argv[i];
    }

    if (n_op < 2) {
        fprintf(stderr, "c_cp: missing operand\n");
        return 1;
    }

    int is_multi = (n_op > 2);

    if (!is_multi && n_op == 2) {
        struct stat st_dir;
        if (stat(operands[1], &st_dir) == 0 && S_ISDIR(st_dir.st_mode)) {
            is_multi = 1;
        }
    }

    if (is_multi) {
        struct stat st;
        if (stat(operands[n_op - 1], &st) != 0) {
            fprintf(stderr, "c_cp: %s: %s\n", operands[n_op - 1], strerror(errno));
            return 1;
        }
        if (!S_ISDIR(st.st_mode)) {
            fprintf(stderr, "c_cp: %s: not a directory\n", operands[n_op - 1]);
            return 1;
        }
    }

    int n_sources = is_multi ? n_op - 1 : 1;
    int any_failure = 0;

    for (int s = 0; s < n_sources; s++) {
        const char *src = operands[s];
        const char *dst;
        char *dst_heap = NULL;

        if (is_multi) {
            const char *dir = operands[n_op - 1];
            const char *base = get_basename(src);
            size_t dlen = strlen(dir);
            size_t blen = strlen(base);
            int slash_needed = !(dlen > 0 && dir[dlen - 1] == '/');
            dst_heap = malloc(dlen + (slash_needed ? 1 : 0) + blen + 1);
            if (!dst_heap) {
                fprintf(stderr, "c_cp: out of memory\n");
                return 1;
            }
            memcpy(dst_heap, dir, dlen);
            if (slash_needed) dst_heap[dlen] = '/';
            memcpy(dst_heap + dlen + (slash_needed ? 1 : 0), base, blen + 1);
            dst = dst_heap;
        } else {
            dst = operands[1];
        }

        int rc = recursive ? copy_recursive(src, dst, force, interactive)
                           : copy_path(src, dst, force, interactive);
        if (rc != 0) {
            any_failure = 1;
        }
        free(dst_heap);
    }

    return any_failure ? 1 : 0;
}
