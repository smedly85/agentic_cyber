#define _POSIX_C_SOURCE 200809L

#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

struct record {
    const unsigned char *ptr;
    size_t len;
};

static int cmp_records(const void *a, const void *b)
{
    const struct record *ra = (const struct record *)a;
    const struct record *rb = (const struct record *)b;
    size_t minlen = ra->len < rb->len ? ra->len : rb->len;
    int c = memcmp(ra->ptr, rb->ptr, minlen);
    if (c != 0)
        return c;
    if (ra->len < rb->len)
        return -1;
    if (ra->len > rb->len)
        return 1;
    return 0;
}

static void fail(const char *msg)
{
    size_t i = 0;
    while (msg[i] != '\0')
        i++;
    (void)write(2, msg, i);
    (void)write(2, "\n", 1);
    exit(2);
}

static int write_all(int fd, const void *buf, size_t len)
{
    const unsigned char *p = (const unsigned char *)buf;
    size_t off = 0;
    while (off < len) {
        ssize_t n = write(fd, p + off, len - off);
        if (n < 0) {
            if (errno == EINTR)
                continue;
            return -1;
        }
        off += (size_t)n;
    }
    return 0;
}

int main(int argc, char *argv[])
{
    /* Validate arguments: only zero args or exactly one "--" is accepted.
       Any other argument is an unknown option or a file operand. */
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--") == 0) {
            if (i + 1 < argc) {
                fprintf(stderr, "sort: unrecognized option '%s'\nTry 'sort --help' for more information.\n", argv[i + 1]);
                exit(2);
            }
            break;
        }
        if (argv[i][0] == '-' && argv[i][1] != '\0') {
            fprintf(stderr, "sort: unrecognized option '%s'\nTry 'sort --help' for more information.\n", argv[i]);
            exit(2);
        }
        /* File operand: attempt to open; report I/O error on failure. */
        int fd = open(argv[i], O_RDONLY);
        if (fd < 0) {
            fprintf(stderr, "sort: cannot read: %s: %s\n", argv[i], strerror(errno));
            exit(2);
        }
        close(fd);
        fprintf(stderr, "sort: unrecognized option '%s'\nTry 'sort --help' for more information.\n", argv[i]);
        exit(2);
    }

    /* Read all of stdin into a dynamically growing buffer. */
    size_t cap = 65536;
    size_t len = 0;
    unsigned char *buf = malloc(cap);
    if (buf == NULL)
        fail("sort: out of memory");

    for (;;) {
        if (len >= cap) {
            size_t newcap = cap * 2;
            if (newcap < cap)
                fail("sort: out of memory");
            unsigned char *tmp = realloc(buf, newcap);
            if (tmp == NULL) {
                free(buf);
                fail("sort: out of memory");
            }
            buf = tmp;
            cap = newcap;
        }
        ssize_t n = read(0, buf + len, cap - len);
        if (n < 0) {
            if (errno == EINTR)
                continue;
            free(buf);
            fail("sort: read error");
        }
        if (n == 0)
            break;
        len += (size_t)n;
    }

    /* Empty input: emit nothing, exit 0. */
    if (len == 0) {
        free(buf);
        return 0;
    }

    /* Count records. */
    size_t nrec = 0;
    for (size_t i = 0; i < len; i++) {
        if (buf[i] == '\n')
            nrec++;
    }
    if (buf[len - 1] != '\n')
        nrec++;

    struct record *recs = malloc(nrec * sizeof(*recs));
    if (recs == NULL) {
        free(buf);
        fail("sort: out of memory");
    }

    /* Partition buffer into records (pointers into buf). */
    size_t idx = 0;
    size_t start = 0;
    for (size_t i = 0; i < len; i++) {
        if (buf[i] == '\n') {
            recs[idx].ptr = buf + start;
            recs[idx].len = i - start;
            idx++;
            start = i + 1;
        }
    }
    if (start < len) {
        recs[idx].ptr = buf + start;
        recs[idx].len = len - start;
        idx++;
    }

    /* Sort records (unsigned bytewise lexicographic). */
    if (nrec > 1)
        qsort(recs, nrec, sizeof(*recs), cmp_records);

    /* Emit each record followed by a newline. */
    unsigned char nl = '\n';
    for (size_t i = 0; i < nrec; i++) {
        if (recs[i].len > 0) {
            if (write_all(1, recs[i].ptr, recs[i].len) != 0) {
                free(recs);
                free(buf);
                fail("sort: write error");
            }
        }
        if (write_all(1, &nl, 1) != 0) {
            free(recs);
            free(buf);
            fail("sort: write error");
        }
    }

    free(recs);
    free(buf);
    return 0;
}
