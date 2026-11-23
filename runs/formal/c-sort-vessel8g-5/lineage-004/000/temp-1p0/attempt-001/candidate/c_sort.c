#define _POSIX_C_SOURCE 200809L
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <fcntl.h>
#include <unistd.h>

typedef struct {
    const unsigned char *data;
    size_t len;
} Record;

static int cmp_records(const void *pa, const void *pb)
{
    const Record *a = (const Record *)pa;
    const Record *b = (const Record *)pb;
    size_t min_len = a->len < b->len ? a->len : b->len;
    int c = memcmp(a->data, b->data, min_len);
    if (c != 0)
        return c;
    if (a->len < b->len)
        return -1;
    if (a->len > b->len)
        return 1;
    return 0;
}

int main(int argc, char *argv[])
{
    /* ---- argument validation ---- */
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--") == 0) {
            /* -- ends options; any operand after it is not permitted */
            for (int j = i + 1; j < argc; j++) {
                fprintf(stderr, "sort: extra operand '%s'\n"
                                "Try 'sort --help' for more information.\n",
                        argv[j]);
                return 2;
            }
            break;
        }
        if (argv[i][0] == '-' && argv[i][1] != '\0') {
            fprintf(stderr, "sort: unrecognized option '%s'\n"
                            "Try 'sort --help' for more information.\n",
                    argv[i]);
            return 2;
        }
        /* Operand (including bare "-") */
        {
            int fd = open(argv[i], O_RDONLY);
            if (fd == -1) {
                fprintf(stderr, "sort: cannot read: %s: %s\n",
                        argv[i], strerror(errno));
                return 2;
            }
            close(fd);
            fprintf(stderr, "sort: extra operand '%s'\n"
                            "Try 'sort --help' for more information.\n",
                    argv[i]);
            return 2;
        }
    }

    signal(SIGPIPE, SIG_IGN);

    /* ---- read all of stdin ---- */
    size_t cap = 65536;
    size_t len = 0;
    unsigned char *buf = malloc(cap);
    if (!buf) {
        fputs("c_sort: memory allocation failed\n", stderr);
        return 2;
    }
    for (;;) {
        if (len >= cap) {
            size_t newcap = cap * 2;
            if (newcap < cap) {
                free(buf);
                fputs("c_sort: input too large\n", stderr);
                return 2;
            }
            unsigned char *nb = realloc(buf, newcap);
            if (!nb) {
                free(buf);
                fputs("c_sort: memory allocation failed\n", stderr);
                return 2;
            }
            buf = nb;
            cap = newcap;
        }
        size_t n = fread(buf + len, 1, cap - len, stdin);
        if (n == 0) {
            if (ferror(stdin)) {
                free(buf);
                fputs("c_sort: read error on stdin\n", stderr);
                return 2;
            }
            break; /* EOF */
        }
        len += n;
    }

    /* ---- parse records ---- */
    size_t nrecs = 0;
    size_t recs_cap = 64;
    Record *recs = malloc(recs_cap * sizeof(Record));
    if (!recs) {
        free(buf);
        fputs("c_sort: memory allocation failed\n", stderr);
        return 2;
    }

    size_t pos = 0;
    while (pos < len) {
        size_t nl = pos;
        while (nl < len && buf[nl] != '\n')
            nl++;
        size_t reclen = nl - pos;

        if (nrecs == recs_cap) {
            size_t newcap = recs_cap * 2;
            if (newcap < recs_cap) {
                free(recs);
                free(buf);
                fputs("c_sort: too many records\n", stderr);
                return 2;
            }
            Record *nr = realloc(recs, newcap * sizeof(Record));
            if (!nr) {
                free(recs);
                free(buf);
                fputs("c_sort: memory allocation failed\n", stderr);
                return 2;
            }
            recs = nr;
            recs_cap = newcap;
        }

        recs[nrecs].data = buf + pos;
        recs[nrecs].len = reclen;
        nrecs++;

        if (nl < len)
            pos = nl + 1;
        else
            pos = len;
    }

    /* ---- sort ---- */
    if (nrecs > 1)
        qsort(recs, nrecs, sizeof(Record), cmp_records);

    /* ---- write output ---- */
    for (size_t i = 0; i < nrecs; i++) {
        if (recs[i].len > 0) {
            size_t written = fwrite(recs[i].data, 1, recs[i].len, stdout);
            if (written != recs[i].len) {
                free(recs);
                free(buf);
                fputs("c_sort: write error on stdout\n", stderr);
                return 2;
            }
        }
        if (fputc('\n', stdout) == EOF) {
            free(recs);
            free(buf);
                fputs("c_sort: write error on stdout\n", stderr);
                return 2;
        }
    }

    if (fflush(stdout) != 0) {
        free(recs);
        free(buf);
        fputs("c_sort: write error on stdout\n", stderr);
        return 2;
    }

    free(recs);
    free(buf);
    return 0;
}
