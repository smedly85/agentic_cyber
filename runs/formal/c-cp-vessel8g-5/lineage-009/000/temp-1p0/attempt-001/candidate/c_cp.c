#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/stat.h>
#include <errno.h>

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

int copy_path(const char *src, const char *dst) {
    struct stat src_stat;
    if (stat(src, &src_stat) != 0)
        return -1;
    if (!S_ISREG(src_stat.st_mode))
        return -1;

    struct stat dst_stat;
    int dst_exists = (stat(dst, &dst_stat) == 0);

    if (dst_exists) {
        if (!S_ISREG(dst_stat.st_mode))
            return -1;
        if (src_stat.st_dev == dst_stat.st_dev &&
            src_stat.st_ino == dst_stat.st_ino)
            return -1;
    } else {
        struct stat lst;
        if (lstat(dst, &lst) == 0 && S_ISLNK(lst.st_mode))
            return -1;
    }

    int sfd = open(src, O_RDONLY);
    if (sfd < 0)
        return -1;

    int dfd;
    if (dst_exists) {
        dfd = open(dst, O_WRONLY | O_TRUNC);
    } else {
        dfd = open(dst, O_WRONLY | O_CREAT | O_TRUNC,
                   (mode_t)(src_stat.st_mode & 0777));
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

int main(int argc, char *argv[]) {
    int *operand_idx = malloc((size_t)argc * sizeof(*operand_idx));
    if (!operand_idx) {
        fprintf(stderr, "c_cp: out of memory\n");
        return 1;
    }

    int n_operands = 0;
    int after_ddash = 0;

    for (int i = 1; i < argc; i++) {
        if (!after_ddash) {
            if (strcmp(argv[i], "--") == 0) {
                after_ddash = 1;
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
        char *heap = NULL;

        if (use_dir) {
            const char *base = strrchr(src, '/');
            base = base ? base + 1 : src;
            size_t dlen = strlen(dir_path);
            size_t blen = strlen(base);
            heap = malloc(dlen + 1 + blen + 1);
            if (!heap) {
                fprintf(stderr, "c_cp: %s: out of memory\n", src);
                any_failure = 1;
                continue;
            }
            memcpy(heap, dir_path, dlen);
            heap[dlen] = '/';
            memcpy(heap + dlen + 1, base, blen + 1);
            dst = heap;
        } else {
            dst = argv[operand_idx[1]];
        }

        if (copy_path(src, dst) != 0) {
            fprintf(stderr, "c_cp: %s: %s\n", src, strerror(errno));
            any_failure = 1;
        }

        free(heap);
    }

    free(operand_idx);
    return any_failure ? 1 : 0;
}
