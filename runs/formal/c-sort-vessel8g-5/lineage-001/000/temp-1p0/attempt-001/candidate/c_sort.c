#define _POSIX_C_SOURCE 200809L

#include <errno.h>
#include <fcntl.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <stdio.h>

#define INITIAL_CAPACITY 1024
#define INITIAL_RECORDS 128

static ssize_t xread(int fd, void *buf, size_t count) {
    ssize_t total = 0;
    char *ptr = (char *)buf;
    while (count > 0) {
        ssize_t n = read(fd, ptr, count);
        if (n < 0) {
            if (errno == EINTR) continue;
            return -1;
        }
        if (n == 0) break;
        total += n;
        ptr += n;
        count -= n;
    }
    return total;
}

static ssize_t xwrite(int fd, const void *buf, size_t count) {
    size_t total = 0;
    const char *ptr = (const char *)buf;
    while (count > 0) {
        ssize_t n = write(fd, ptr, count);
        if (n < 0) {
            if (errno == EINTR) continue;
            return -1;
        }
        total += n;
        ptr += n;
        count -= n;
    }
    return (ssize_t)total;
}

typedef struct {
    char *ptr;
    size_t len;
} Record;

static int compare_records(const void *a, const void *b) {
    const Record *ra = (const Record *)a;
    const Record *rb = (const Record *)b;
    size_t minlen = ra->len < rb->len ? ra->len : rb->len;
    int cmp = memcmp(ra->ptr, rb->ptr, minlen);
    if (cmp != 0) return cmp;
    return ra->len < rb->len ? -1 : (ra->len > rb->len ? 1 : 0);
}

int main(int argc, char *argv[]) {
    if (argc < 1) return 2;

    const char *progname = argv[0];

    if (argc > 1) {
        int i = 1;
        while (i < argc) {
            const char *arg = argv[i];
            if (strcmp(arg, "--") == 0) {
                i++;
                if (i < argc) {
                    fprintf(stderr, "%s: extra operand '%s'\n", progname, argv[i]);
                    return 2;
                }
                break;
            }
            if (arg[0] == '-' && arg[1] != '\0') {
                if (arg[1] == '-') {
                    fprintf(stderr, "%s: unrecognized option '--%s'\n", progname, arg + 2);
                } else {
                    fprintf(stderr, "%s: unrecognized option '-%c'\n", progname, arg[1]);
                }
                fprintf(stderr, "Try '%s --help' for more information.\n", progname);
                return 2;
            } else {
                int fd = open(arg, O_RDONLY);
                if (fd < 0) {
                    fprintf(stderr, "%s: cannot read: %s: %s\n", progname, arg, strerror(errno));
                    return 2;
                }
                close(fd);
            }
            i++;
        }
    }

    char *buffer = NULL;
    size_t buffer_size = 0;
    size_t buffer_used = 0;

    buffer = (char *)malloc(INITIAL_CAPACITY);
    if (!buffer) {
        fprintf(stderr, "sort: memory allocation failed\n");
        return 2;
    }
    buffer_size = INITIAL_CAPACITY;

    while (1) {
        if (buffer_used >= buffer_size) {
            size_t new_size = buffer_size * 2;
            if (new_size == 0) new_size = 1;
            char *new_buffer = (char *)realloc(buffer, new_size);
            if (!new_buffer) {
                fprintf(stderr, "sort: memory allocation failed\n");
                free(buffer);
                return 2;
            }
            buffer = new_buffer;
            buffer_size = new_size;
        }

        ssize_t n = xread(STDIN_FILENO, buffer + buffer_used, buffer_size - buffer_used);
        if (n < 0) {
            fprintf(stderr, "sort: read error\n");
            free(buffer);
            return 2;
        }
        if (n == 0) break;
        buffer_used += n;
    }

    if (buffer_used == 0) {
        free(buffer);
        return 0;
    }

    Record *records = NULL;
    size_t record_capacity = 0;
    size_t record_count = 0;

    records = (Record *)malloc(INITIAL_RECORDS * sizeof(Record));
    if (!records) {
        fprintf(stderr, "sort: memory allocation failed\n");
        free(buffer);
        return 2;
    }
    record_capacity = INITIAL_RECORDS;

    char *start = buffer;
    for (size_t i = 0; i < buffer_used; i++) {
        if (buffer[i] == '\n') {
            if (record_count >= record_capacity) {
                size_t new_capacity = record_capacity * 2;
                Record *new_records = (Record *)realloc(records, new_capacity * sizeof(Record));
                if (!new_records) {
                    fprintf(stderr, "sort: memory allocation failed\n");
                    free(buffer);
                    free(records);
                    return 2;
                }
                records = new_records;
                record_capacity = new_capacity;
            }
            records[record_count].ptr = start;
            records[record_count].len = (size_t)(buffer + i - start);
            record_count++;
            start = buffer + i + 1;
        }
    }

    if (start < buffer + buffer_used) {
        if (record_count >= record_capacity) {
            size_t new_capacity = record_capacity * 2;
            Record *new_records = (Record *)realloc(records, new_capacity * sizeof(Record));
            if (!new_records) {
                fprintf(stderr, "sort: memory allocation failed\n");
                free(buffer);
                free(records);
                return 2;
            }
            records = new_records;
            record_capacity = new_capacity;
        }
        records[record_count].ptr = start;
        records[record_count].len = (size_t)(buffer + buffer_used - start);
        record_count++;
    }

    qsort(records, record_count, sizeof(Record), compare_records);

    for (size_t i = 0; i < record_count; i++) {
        if (xwrite(STDOUT_FILENO, records[i].ptr, records[i].len) < 0) {
            fprintf(stderr, "sort: write error\n");
            free(buffer);
            free(records);
            return 2;
        }
        if (xwrite(STDOUT_FILENO, "\n", 1) < 0) {
            fprintf(stderr, "sort: write error\n");
            free(buffer);
            free(records);
            return 2;
        }
    }

    free(buffer);
    free(records);
    return 0;
}
