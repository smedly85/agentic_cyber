#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static int write_all(int fd, const void *buf, size_t len) {
    const unsigned char *p = (const unsigned char *)buf;
    size_t remaining = len;
    while (remaining > 0) {
        ssize_t n = write(fd, p, remaining);
        if (n < 0) {
            if (errno == EINTR)
                continue;
            return -1;
        }
        p += (size_t)n;
        remaining -= (size_t)n;
    }
    return 0;
}

static int find_in_line(const unsigned char *line, size_t line_len,
                        const unsigned char *pattern, size_t pattern_len) {
    if (pattern_len == 0)
        return 1;
    if (pattern_len > line_len)
        return 0;
    for (size_t i = 0; i <= line_len - pattern_len; i++) {
        if (memcmp(line + i, pattern, pattern_len) == 0)
            return 1;
    }
    return 0;
}

static int search_stream(int fd, const unsigned char *pattern, size_t pattern_len,
                         const char *prefix, size_t prefix_len, int *found) {
    int error = 0;
    unsigned char *line_buf = NULL;
    size_t line_len = 0;
    size_t line_cap = 0;
    unsigned char chunk[8192];

    for (;;) {
        ssize_t n = read(fd, chunk, sizeof(chunk));
        if (n < 0) {
            if (errno == EINTR)
                continue;
            error = 1;
            break;
        }
        if (n == 0)
            break;

        for (ssize_t i = 0; i < n; i++) {
            if (chunk[i] == 0x0A) {
                if (find_in_line(line_buf, line_len, pattern, pattern_len)) {
                    if (found)
                        *found = 1;
                    if (prefix_len > 0 &&
                        write_all(STDOUT_FILENO, prefix, prefix_len) != 0) {
                        error = 1;
                        goto out;
                    }
                    if (line_len > 0 &&
                        write_all(STDOUT_FILENO, line_buf, line_len) != 0) {
                        error = 1;
                        goto out;
                    }
                    if (write_all(STDOUT_FILENO, "\n", 1) != 0) {
                        error = 1;
                        goto out;
                    }
                }
                line_len = 0;
            } else {
                if (line_len + 1 > line_cap) {
                    size_t new_cap;
                    if (line_cap == 0)
                        new_cap = 256;
                    else if (line_cap > (size_t)-1 / 2) {
                        error = 1;
                        goto out;
                    } else {
                        new_cap = line_cap * 2;
                    }
                    if (new_cap < line_len + 1)
                        new_cap = line_len + 1;
                    unsigned char *tmp = realloc(line_buf, new_cap);
                    if (!tmp) {
                        error = 1;
                        goto out;
                    }
                    line_buf = tmp;
                    line_cap = new_cap;
                }
                line_buf[line_len++] = chunk[i];
            }
        }
    }

    if (line_len > 0) {
        if (find_in_line(line_buf, line_len, pattern, pattern_len)) {
            if (found)
                *found = 1;
            if (prefix_len > 0 &&
                write_all(STDOUT_FILENO, prefix, prefix_len) != 0) {
                error = 1;
                goto out;
            }
            if (write_all(STDOUT_FILENO, line_buf, line_len) != 0) {
                error = 1;
                goto out;
            }
            if (write_all(STDOUT_FILENO, "\n", 1) != 0) {
                error = 1;
                goto out;
            }
        }
    }

out:
    free(line_buf);
    return error;
}

int main(int argc, char **argv) {
    const char *prog = (argc > 0) ? argv[0] : "c_grep";
    const char *pattern = NULL;
    int i = 1;
    int saw_ddash = 0;

    while (i < argc) {
        if (!saw_ddash) {
            if (strcmp(argv[i], "--") == 0) {
                saw_ddash = 1;
                i++;
                continue;
            }
            if (argv[i][0] == '-' && argv[i][1] != '\0') {
                fprintf(stderr, "%s: unsupported option: %s\n", prog, argv[i]);
                fprintf(stderr, "usage: %s PATTERN [FILE...]\n", prog);
                return 2;
            }
        }
        pattern = argv[i];
        i++;
        break;
    }

    if (!pattern) {
        fprintf(stderr, "usage: %s PATTERN [FILE...]\n", prog);
        return 2;
    }

    size_t pattern_len = strlen(pattern);
    int nfiles = argc - i;
    const char **files = (nfiles > 0) ? &argv[i] : NULL;
    int found_any = 0;
    int any_error = 0;

    if (nfiles == 0) {
        if (search_stream(STDIN_FILENO, (const unsigned char *)pattern,
                          pattern_len, NULL, 0, &found_any))
            any_error = 1;
    } else if (nfiles == 1) {
        int fd = open(files[0], O_RDONLY);
        if (fd < 0) {
            fprintf(stderr, "%s: %s: %s\n", prog, files[0], strerror(errno));
            any_error = 1;
        } else {
            struct stat st;
            if (fstat(fd, &st) == 0 && S_ISDIR(st.st_mode)) {
                fprintf(stderr, "%s: %s: %s\n", prog, files[0], strerror(EISDIR));
                any_error = 1;
            } else {
                if (search_stream(fd, (const unsigned char *)pattern,
                                  pattern_len, NULL, 0, &found_any))
                    any_error = 1;
            }
            close(fd);
        }
    } else {
        for (int f = 0; f < nfiles; f++) {
            size_t op_len = strlen(files[f]);
            char *prefix = (char *)malloc(op_len + 2);
            if (!prefix) {
                fprintf(stderr, "%s: %s: %s\n", prog, files[f], strerror(ENOMEM));
                any_error = 1;
                continue;
            }
            memcpy(prefix, files[f], op_len);
            prefix[op_len] = ':';
            prefix[op_len + 1] = '\0';

            int fd = open(files[f], O_RDONLY);
            if (fd < 0) {
                fprintf(stderr, "%s: %s: %s\n", prog, files[f], strerror(errno));
                any_error = 1;
                free(prefix);
                continue;
            }
            struct stat st;
            if (fstat(fd, &st) == 0 && S_ISDIR(st.st_mode)) {
                fprintf(stderr, "%s: %s: %s\n", prog, files[f], strerror(EISDIR));
                any_error = 1;
                close(fd);
                free(prefix);
                continue;
            }
            if (search_stream(fd, (const unsigned char *)pattern,
                              pattern_len, prefix, op_len + 1, &found_any))
                any_error = 1;
            close(fd);
            free(prefix);
        }
    }

    if (any_error)
        return 2;
    return found_any ? 0 : 1;
}
