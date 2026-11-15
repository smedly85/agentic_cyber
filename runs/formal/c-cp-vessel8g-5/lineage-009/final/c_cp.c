#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/stat.h>
#include <errno.h>
#include <dirent.h>
#include <limits.h>

#ifndef PATH_MAX
#define PATH_MAX 4096
#endif

static int copy_file_data(int src_fd, int dst_fd) {
    char buf[65536];
    for (;;) {
        ssize_t nread = read(src_fd, buf, sizeof(buf));
        if (nread < 0) {
            if (errno == EINTR)
                continue;
            return -1;
        }
        if (nread == 0)
            break;
        ssize_t written = 0;
        while (written < nread) {
            ssize_t nw = write(dst_fd, buf + written, (size_t)(nread - written));
            if (nw < 0) {
                if (errno == EINTR)
                    continue;
                return -1;
            }
            written += nw;
        }
    }
    return 0;
}

int copy_path(const char *src, const char *dst, int force, int interactive) {
    struct stat src_stat;
    if (stat(src, &src_stat) != 0)
        return -1;
    if (!S_ISREG(src_stat.st_mode))
        return -1;

    /* Pre-checks: reject directory destinations and self-copy before
       any destructive action. */
    struct stat dst_stat;
    int dst_resolves = (stat(dst, &dst_stat) == 0);
    if (dst_resolves) {
        if (S_ISDIR(dst_stat.st_mode))
            return -1;
        if (src_stat.st_dev == dst_stat.st_dev &&
            src_stat.st_ino == dst_stat.st_ino)
            return -1;
    } else {
        struct stat lst;
        if (lstat(dst, &lst) == 0 && S_ISLNK(lst.st_mode)) {
            errno = ENOLINK;
            return -1;
        }
    }

    if (interactive && dst_resolves) {
        fprintf(stderr, "overwrite %s? ", dst);
        fflush(stderr);
        char line[64];
        if (fgets(line, sizeof(line), stdin) == NULL ||
            (line[0] != 'y' && line[0] != 'Y'))
            return -2;
    }

    int sfd = open(src, O_RDONLY);
    if (sfd < 0)
        return -1;

    int dfd = -1;

    /* Try to open the destination for writing.
       - Existing regular file (or symlink→regular): O_WRONLY|O_TRUNC works.
       - Missing path: ENOENT, fall through to O_CREAT.
       - Dangling symlink: ENOLINK (handled above). */
    dfd = open(dst, O_WRONLY | O_TRUNC);
    if (dfd < 0) {
        dfd = open(dst, O_WRONLY | O_CREAT | O_TRUNC,
                   (mode_t)(src_stat.st_mode & 0777));
    }
    if (dfd < 0 && force) {
        /* Force: remove existing non-directory entry and create fresh. */
        struct stat lst;
        if (lstat(dst, &lst) == 0 && !S_ISDIR(lst.st_mode)) {
            if (unlink(dst) == 0) {
                dfd = open(dst, O_WRONLY | O_CREAT | O_TRUNC,
                           (mode_t)(src_stat.st_mode & 0777));
            }
        }
    }
    if (dfd < 0) {
        close(sfd);
        return -1;
    }

    int rc = copy_file_data(sfd, dfd);
    close(sfd);
    close(dfd);
    return rc;
}

static int is_self_copy(const char *src, const char *dest) {
    /* Same inode? */
    struct stat sst, dst_st;
    if (stat(src, &sst) == 0 && stat(dest, &dst_st) == 0) {
        if (sst.st_dev == dst_st.st_dev && sst.st_ino == dst_st.st_ino)
            return 1;
    }

    /* Dest is a path below src? (lexical, after absolutizing) */
    char cwd[PATH_MAX];
    if (getcwd(cwd, sizeof(cwd)) == 0)
        return 0;

    size_t src_len;
    const char *src_abs;
    char *src_heap = NULL;
    if (src[0] == '/') {
        src_abs = src;
        src_len = strlen(src);
    } else {
        src_len = strlen(cwd) + 1 + strlen(src);
        src_heap = malloc(src_len + 1);
        if (!src_heap)
            return 0;
        snprintf(src_heap, src_len + 1, "%s/%s", cwd, src);
        src_abs = src_heap;
    }

    const char *dest_abs;
    char *dest_heap = NULL;
    if (dest[0] == '/') {
        dest_abs = dest;
    } else {
        size_t dst_total = strlen(cwd) + 1 + strlen(dest);
        dest_heap = malloc(dst_total + 1);
        if (!dest_heap) {
            free(src_heap);
            return 0;
        }
        snprintf(dest_heap, dst_total + 1, "%s/%s", cwd, dest);
        dest_abs = dest_heap;
    }

    int result = 0;
    size_t dest_strlen = strlen(dest_abs);
    if (dest_strlen > src_len &&
        strncmp(dest_abs, src_abs, src_len) == 0 &&
        dest_abs[src_len] == '/')
        result = 1;

    free(src_heap);
    free(dest_heap);
    return result;
}

static int recursive_copy(const char *src, const char *dst, int force, int interactive) {
    DIR *dir = opendir(src);
    if (!dir)
        return -1;
    int any_failure = 0;
    struct dirent *entry;
    while ((entry = readdir(dir)) != NULL) {
        if (strcmp(entry->d_name, ".") == 0 || strcmp(entry->d_name, "..") == 0)
            continue;
        char src_path[PATH_MAX], dst_path[PATH_MAX];
        if (snprintf(src_path, sizeof(src_path), "%s/%s", src, entry->d_name) >= (int)sizeof(src_path) ||
            snprintf(dst_path, sizeof(dst_path), "%s/%s", dst, entry->d_name) >= (int)sizeof(dst_path)) {
            any_failure = 1;
            continue;
        }
        struct stat st;
        if (lstat(src_path, &st) != 0) {
            any_failure = 1;
            continue;
        }
        if (S_ISREG(st.st_mode)) {
            if (copy_path(src_path, dst_path, force, interactive) != 0)
                any_failure = 1;
        } else if (S_ISDIR(st.st_mode)) {
            if (mkdir(dst_path, (mode_t)(st.st_mode & 0777)) != 0 && errno != EEXIST) {
                any_failure = 1;
                continue;
            }
            if (recursive_copy(src_path, dst_path, force, interactive) != 0)
                any_failure = 1;
        } else if (S_ISLNK(st.st_mode)) {
            char target[PATH_MAX];
            ssize_t tlen = readlink(src_path, target, sizeof(target) - 1);
            if (tlen < 0) {
                any_failure = 1;
                continue;
            }
            target[tlen] = '\0';
            struct stat dst_st;
            if (lstat(dst_path, &dst_st) == 0) {
                if (S_ISDIR(dst_st.st_mode)) {
                    any_failure = 1;
                    continue;
                }
                if (unlink(dst_path) != 0) {
                    any_failure = 1;
                    continue;
                }
            }
            if (symlink(target, dst_path) != 0)
                any_failure = 1;
        } else {
            any_failure = 1;
        }
    }
    closedir(dir);
    return any_failure ? -1 : 0;
}

int main(int argc, char *argv[]) {
    int *operand_idx = malloc((size_t)argc * sizeof(*operand_idx));
    if (!operand_idx) {
        fprintf(stderr, "c_cp: out of memory\n");
        return 1;
    }

    int n_operands = 0;
    int after_ddash = 0;
    int force = 0;
    int interactive = 0;
    int recursive = 0;

    for (int i = 1; i < argc; i++) {
        if (!after_ddash) {
            if (strcmp(argv[i], "--") == 0) {
                after_ddash = 1;
                continue;
            }
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
            if (argv[i][0] == '-' && argv[i][1] != '\0') {
                fprintf(stderr, "c_cp: unknown option: %s\n", argv[i]);
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

    int use_dir = 0;
    const char *dir_path = NULL;

    {
        const char *last = argv[operand_idx[n_operands - 1]];
        struct stat dstat;
        if (stat(last, &dstat) == 0 && S_ISDIR(dstat.st_mode)) {
            use_dir = 1;
            dir_path = last;
        } else if (n_operands > 2) {
            fprintf(stderr, "c_cp: %s: not a directory\n", last);
            free(operand_idx);
            return 1;
        }
    }

    int n_sources = use_dir ? n_operands - 1 : 1;
    int any_failure = 0;

    for (int i = 0; i < n_sources; i++) {
        const char *src = argv[operand_idx[i]];
        const char *dst;

        /* Resolve dst (same logic as before for non-recursive; recursive
           branches use the same dst). */
        if (use_dir) {
            const char *base = strrchr(src, '/');
            base = base ? base + 1 : src;
            size_t dlen = strlen(dir_path);
            size_t blen = strlen(base);
            char *heap = malloc(dlen + 1 + blen + 1);
            if (!heap) {
                fprintf(stderr, "c_cp: %s: out of memory\n", src);
                any_failure = 1;
                continue;
            }
            memcpy(heap, dir_path, dlen);
            heap[dlen] = '/';
            memcpy(heap + dlen + 1, base, blen + 1);
            dst = heap;

            if (recursive) {
                struct stat rst;
                if (lstat(src, &rst) != 0) {
                    fprintf(stderr, "c_cp: %s: %s\n", src, strerror(errno));
                    free(heap);
                    any_failure = 1;
                    continue;
                }
                if (S_ISDIR(rst.st_mode)) {
                    if (is_self_copy(src, dst)) {
                        fprintf(stderr, "c_cp: %s: cannot copy a directory into itself\n", src);
                        free(heap);
                        any_failure = 1;
                        continue;
                    }
                    struct stat mstat;
                    if (stat(dst, &mstat) != 0 || !S_ISDIR(mstat.st_mode)) {
                        if (mkdir(dst, (mode_t)(rst.st_mode & 0777)) != 0) {
                            fprintf(stderr, "c_cp: %s: %s\n", src, strerror(errno));
                            free(heap);
                            any_failure = 1;
                            continue;
                        }
                    }
                    if (recursive_copy(src, dst, force, interactive) != 0) {
                        fprintf(stderr, "c_cp: %s: failure in recursive copy\n", src);
                        any_failure = 1;
                    }
                } else if (S_ISLNK(rst.st_mode)) {
                    char target[PATH_MAX];
                    ssize_t tlen = readlink(src, target, sizeof(target) - 1);
                    if (tlen < 0) {
                        fprintf(stderr, "c_cp: %s: %s\n", src, strerror(errno));
                        free(heap);
                        any_failure = 1;
                        continue;
                    }
                    target[tlen] = '\0';
                    struct stat dstat2;
                    if (lstat(dst, &dstat2) == 0) {
                        if (S_ISDIR(dstat2.st_mode)) {
                            fprintf(stderr, "c_cp: %s: destination is a directory\n", src);
                            free(heap);
                            any_failure = 1;
                            continue;
                        }
                        unlink(dst);
                    }
                    if (symlink(target, dst) != 0) {
                        fprintf(stderr, "c_cp: %s: %s\n", src, strerror(errno));
                        any_failure = 1;
                    }
                } else if (S_ISREG(rst.st_mode)) {
                    int rc = copy_path(src, dst, force, interactive);
                    if (rc != 0) {
                        if (rc != -2)
                            fprintf(stderr, "c_cp: %s: %s\n", src, strerror(errno));
                        any_failure = 1;
                    }
                } else {
                    fprintf(stderr, "c_cp: %s: unsupported file type\n", src);
                    any_failure = 1;
                }
                free(heap);
                continue;
            }

            /* Non-recursive with directory destination */
            int rc = copy_path(src, dst, force, interactive);
            if (rc != 0) {
                if (rc != -2)
                    fprintf(stderr, "c_cp: %s: %s\n", src, strerror(errno));
                any_failure = 1;
            }
            free(heap);
        } else {
            dst = argv[operand_idx[1]];

            if (recursive) {
                struct stat rst;
                if (lstat(src, &rst) != 0) {
                    fprintf(stderr, "c_cp: %s: %s\n", src, strerror(errno));
                    any_failure = 1;
                    continue;
                }
                if (S_ISDIR(rst.st_mode)) {
                    /* Single source, dest is missing or non-directory.
                       If dest is an existing non-directory, error. */
                    struct stat dstat3;
                    if (stat(dst, &dstat3) == 0 && !S_ISDIR(dstat3.st_mode)) {
                        fprintf(stderr, "c_cp: %s: cannot copy to non-directory\n", src);
                        any_failure = 1;
                        continue;
                    }
                    if (is_self_copy(src, dst)) {
                        fprintf(stderr, "c_cp: %s: cannot copy a directory into itself\n", src);
                        any_failure = 1;
                        continue;
                    }
                    if (stat(dst, &dstat3) != 0) {
                        if (mkdir(dst, (mode_t)(rst.st_mode & 0777)) != 0) {
                            fprintf(stderr, "c_cp: %s: %s\n", src, strerror(errno));
                            any_failure = 1;
                            continue;
                        }
                    }
                    if (recursive_copy(src, dst, force, interactive) != 0) {
                        fprintf(stderr, "c_cp: %s: failure in recursive copy\n", src);
                        any_failure = 1;
                    }
                } else if (S_ISLNK(rst.st_mode)) {
                    char target[PATH_MAX];
                    ssize_t tlen = readlink(src, target, sizeof(target) - 1);
                    if (tlen < 0) {
                        fprintf(stderr, "c_cp: %s: %s\n", src, strerror(errno));
                        any_failure = 1;
                        continue;
                    }
                    target[tlen] = '\0';
                    struct stat dstat2;
                    if (lstat(dst, &dstat2) == 0) {
                        if (S_ISDIR(dstat2.st_mode)) {
                            fprintf(stderr, "c_cp: %s: destination is a directory\n", src);
                            any_failure = 1;
                            continue;
                        }
                        unlink(dst);
                    }
                    if (symlink(target, dst) != 0) {
                        fprintf(stderr, "c_cp: %s: %s\n", src, strerror(errno));
                        any_failure = 1;
                    }
                } else if (S_ISREG(rst.st_mode)) {
                    int rc = copy_path(src, dst, force, interactive);
                    if (rc != 0) {
                        if (rc != -2)
                            fprintf(stderr, "c_cp: %s: %s\n", src, strerror(errno));
                        any_failure = 1;
                    }
                } else {
                    fprintf(stderr, "c_cp: %s: unsupported file type\n", src);
                    any_failure = 1;
                }
            } else {
                int rc = copy_path(src, dst, force, interactive);
                if (rc != 0) {
                    if (rc != -2)
                        fprintf(stderr, "c_cp: %s: %s\n", src, strerror(errno));
                    any_failure = 1;
                }
            }
        }
    }

    free(operand_idx);
    return any_failure ? 1 : 0;
}
