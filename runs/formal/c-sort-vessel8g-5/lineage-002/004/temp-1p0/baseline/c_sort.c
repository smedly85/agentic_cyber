#define _POSIX_C_SOURCE 200809L

#include <errno.h>
#include <stdio.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

struct record {
    const unsigned char *ptr;
    size_t len;
    size_t idx;
};

static int reverse_order = 0;
static int fold_case = 0;
static int unique = 0;

static int compare_folded(const struct record *ra, const struct record *rb)
{
    size_t minlen = ra->len < rb->len ? ra->len : rb->len;
    for (size_t i = 0; i < minlen; i++) {
        unsigned char a = ra->ptr[i];
        unsigned char b = rb->ptr[i];
        if (a >= 'A' && a <= 'Z') a = (unsigned char)(a - 'A' + 'a');
        if (b >= 'A' && b <= 'Z') b = (unsigned char)(b - 'A' + 'a');
        if (a != b)
            return (int)a - (int)b;
    }
    if (ra->len < rb->len) return -1;
    if (ra->len > rb->len) return 1;
    return 0;
}

static int compare_bytes(const struct record *ra, const struct record *rb)
{
    size_t minlen = ra->len < rb->len ? ra->len : rb->len;
    int c = memcmp(ra->ptr, rb->ptr, minlen);
    if (c != 0) return c;
    if (ra->len < rb->len) return -1;
    if (ra->len > rb->len) return 1;
    return 0;
}

static int keys_equal(const struct record *a, const struct record *b)
{
    if (fold_case)
        return compare_folded(a, b) == 0;
    if (a->len != b->len) return 0;
    return memcmp(a->ptr, b->ptr, a->len) == 0;
}

static int cmp_records(const void *a, const void *b)
{
    const struct record *ra = (const struct record *)a;
    const struct record *rb = (const struct record *)b;
    int c;

    if (fold_case) {
        c = compare_folded(ra, rb);
    } else {
        c = compare_bytes(ra, rb);
    }

    if (c != 0)
        return reverse_order ? -c : c;

    if (unique) {
        /* Tiebreak by original input position (ascending, unaffected by -r). */
        if (ra->idx < rb->idx) return -1;
        if (ra->idx > rb->idx) return 1;
        return 0;
    }

    /* Non-unique with fold_case: last-resort original-byte comparison. */
    if (fold_case) {
        c = compare_bytes(ra, rb);
        if (c != 0)
            return reverse_order ? -c : c;
    }
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
    int options_done = 0;
    for (int i = 1; i < argc; i++) {
        if (!options_done && strcmp(argv[i], "--") == 0) {
            options_done = 1;
            continue;
        }
        if (!options_done && argv[i][0] == '-' && argv[i][1] == '-' && argv[i][2] != '\0') {
            /* Long option. */
            if (strcmp(argv[i], "--reverse") == 0) {
                reverse_order = 1;
            } else if (strcmp(argv[i], "--ignore-case") == 0) {
                fold_case = 1;
            } else if (strcmp(argv[i], "--unique") == 0) {
                unique = 1;
            } else {
                fprintf(stderr, "sort: unrecognized option '%s'\nTry 'sort --help' for more information.\n", argv[i]);
                exit(2);
            }
            continue;
        }
        if (!options_done && argv[i][0] == '-' && argv[i][1] != '\0') {
            /* Short option cluster: each character after '-' is an option. */
            for (size_t j = 1; argv[i][j] != '\0'; j++) {
                if (argv[i][j] == 'f') {
                    fold_case = 1;
                } else if (argv[i][j] == 'r') {
                    reverse_order = 1;
                } else if (argv[i][j] == 'u') {
                    unique = 1;
                } else {
                    fprintf(stderr, "sort: invalid option -- '%c'\nTry 'sort --help' for more information.\n", argv[i][j]);
                    exit(2);
                }
            }
            continue;
        }
        /* File operand. */
        if (strcmp(argv[i], "-") == 0) {
            fprintf(stderr, "sort: unrecognized option '%s'\nTry 'sort --help' for more information.\n", argv[i]);
            exit(2);
        }
        {
            FILE *f = fopen(argv[i], "rb");
            if (f == NULL) {
                fprintf(stderr, "sort: cannot read: %s: %s\n", argv[i], strerror(errno));
                exit(2);
            }
            fclose(f);
            fprintf(stderr, "sort: file operands are not supported\n");
            exit(2);
        }
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
            recs[idx].idx = idx;
            idx++;
            start = i + 1;
        }
    }
    if (start < len) {
        recs[idx].ptr = buf + start;
        recs[idx].len = len - start;
        recs[idx].idx = idx;
        idx++;
    }

    /* Sort records (unsigned bytewise lexicographic). */
    if (nrec > 1)
        qsort(recs, nrec, sizeof(*recs), cmp_records);

    /* Deduplicate after sorting: equal records are now adjacent;
       keep only the first (lowest input index) of each group. */
    if (unique && nrec > 1) {
        size_t kept = 1;
        for (size_t i = 1; i < nrec; i++) {
            if (!keys_equal(&recs[kept - 1], &recs[i])) {
                recs[kept++] = recs[i];
            }
        }
        nrec = kept;
    }

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
