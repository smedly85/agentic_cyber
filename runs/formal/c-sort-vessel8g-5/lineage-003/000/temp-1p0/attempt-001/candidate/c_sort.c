#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <signal.h>
#include <errno.h>
#include <fcntl.h>
#include <unistd.h>

typedef struct {
    unsigned char *data;
    size_t len;
} Record;

static void
free_records(Record *records, size_t count)
{
    for (size_t i = 0; i < count; i++)
        free(records[i].data);
    free(records);
}

static int
compare_records(const void *a, const void *b)
{
    const Record *ra = (const Record *)a;
    const Record *rb = (const Record *)b;
    size_t minlen = ra->len < rb->len ? ra->len : rb->len;
    int cmp = 0;
    if (minlen > 0)
        cmp = memcmp(ra->data, rb->data, minlen);
    if (cmp != 0)
        return cmp;
    if (ra->len < rb->len) return -1;
    if (ra->len > rb->len) return  1;
    return 0;
}

int
main(int argc, char *argv[])
{
    signal(SIGPIPE, SIG_IGN);

    /* --- argument parsing (no supported options at this checkpoint) --- */
    for (int i = 1; i < argc; i++) {
        const char *arg = argv[i];

        if (strcmp(arg, "--") == 0) {
            /* -- ends option parsing; operands after it are not permitted */
            if (i + 1 < argc) {
                const char *op = argv[i + 1];
                int fd = open(op, O_RDONLY);
                if (fd == -1) {
                    fprintf(stderr, "sort: cannot read: %s: %s\n",
                            op, strerror(errno));
                } else {
                    close(fd);
                    fprintf(stderr, "sort: cannot read: %s: %s\n",
                            op, strerror(EINVAL));
                }
                return 2;
            }
            continue;
        }

        if (arg[0] == '-' && arg[1] != '\0') {
            /* unrecognized option */
            if (arg[1] == '-') {
                fprintf(stderr, "sort: unrecognized option '%s'\n", arg);
            } else {
                fprintf(stderr, "sort: unrecognized option '%c'\n", arg[1]);
            }
            fprintf(stderr, "Try 'sort --help' for more information.\n");
            return 2;
        }

        /* Operand (includes bare "-"): not supported at this checkpoint */
        int fd = open(arg, O_RDONLY);
        if (fd == -1) {
            fprintf(stderr, "sort: cannot read: %s: %s\n",
                    arg, strerror(errno));
        } else {
            close(fd);
            fprintf(stderr, "sort: cannot read: %s: %s\n",
                    arg, strerror(EINVAL));
        }
        return 2;
    }

    /* --- read all records from stdin --- */
    Record  *records = NULL;
    size_t   count    = 0;
    size_t   capacity = 0;
    char    *linebuf  = NULL;
    size_t   linecap  = 0;

    for (;;) {
        ssize_t linelen = getline(&linebuf, &linecap, stdin);
        if (linelen == -1) {
            if (ferror(stdin)) {
                fprintf(stderr, "sort: error reading input\n");
                free(linebuf);
                free_records(records, count);
                return 2;
            }
            break;  /* EOF */
        }

        /* strip trailing newline if present */
        size_t reclen = (linelen > 0 && linebuf[linelen - 1] == '\n')
                        ? (size_t)(linelen - 1)
                        : (size_t)linelen;

        /* grow the records array */
        if (count >= capacity) {
            size_t newcap = capacity ? capacity * 2 : 256;
            Record *tmp = realloc(records, newcap * sizeof *tmp);
            if (!tmp) {
                fprintf(stderr, "sort: out of memory\n");
                free(linebuf);
                free_records(records, count);
                return 2;
            }
            records = tmp;
            capacity = newcap;
        }

        /* copy record bytes (may contain NUL) */
        unsigned char *data = NULL;
        if (reclen > 0) {
            data = malloc(reclen);
            if (!data) {
                fprintf(stderr, "sort: out of memory\n");
                free(linebuf);
                free_records(records, count);
                return 2;
            }
            memcpy(data, linebuf, reclen);
        }

        records[count].data = data;
        records[count].len  = reclen;
        count++;
    }

    free(linebuf);

    /* --- sort --- */
    if (count > 1)
        qsort(records, count, sizeof *records, compare_records);

    /* --- write output --- */
    for (size_t i = 0; i < count; i++) {
        if (records[i].len > 0) {
            if (fwrite(records[i].data, 1, records[i].len, stdout)
                != records[i].len)
                goto write_err;
        }
        if (fputc('\n', stdout) == EOF)
            goto write_err;
    }

    if (fflush(stdout) == EOF)
        goto write_err;

    free_records(records, count);
    return 0;

write_err:
    fprintf(stderr, "sort: error writing output\n");
    free_records(records, count);
    return 2;
}
