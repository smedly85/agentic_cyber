#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

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

int main(int argc, char *argv[])
{
	/* Only "c_sort" or "c_sort --" are valid invocations. */
	int saw_ddash = 0;
	for (int i = 1; i < argc; i++) {
		if (saw_ddash) {
			fprintf(stderr, "sort: cannot read: %s: No such file or directory\n", argv[i]);
			return 2;
		}
		if (strcmp(argv[i], "--") == 0) {
			saw_ddash = 1;
		} else if (argv[i][0] == '-' && strlen(argv[i]) > 1) {
			fprintf(stderr, "sort: unrecognized option '%s'\nTry 'sort --help' for more information.\n", argv[i]);
			return 2;
		} else {
			fprintf(stderr, "sort: cannot read: %s: No such file or directory\n", argv[i]);
			return 2;
		}
	}

	/* Read all of stdin into a growable buffer. */
	size_t cap = 65536;
	unsigned char *buf = malloc(cap);
	if (!buf) {
		fprintf(stderr, "c_sort: out of memory\n");
		return 2;
	}
	size_t len = 0;
	for (;;) {
		if (len == cap) {
			if (cap > SIZE_MAX / 2) {
				free(buf);
				fprintf(stderr, "c_sort: input too large\n");
				return 2;
			}
			cap *= 2;
			unsigned char *nb = realloc(buf, cap);
			if (!nb) {
				free(buf);
				fprintf(stderr, "c_sort: out of memory\n");
				return 2;
			}
			buf = nb;
		}
		size_t n = fread(buf + len, 1, cap - len, stdin);
		len += n;
		if (n == 0) {
			if (ferror(stdin)) {
				free(buf);
				fprintf(stderr, "c_sort: read error\n");
				return 2;
			}
			break;
		}
	}

	if (len == 0) {
		free(buf);
		return 0;
	}

	/* Count records: one per newline, plus one more if last byte isn't newline. */
	size_t nrecs = 0;
	for (size_t i = 0; i < len; i++) {
		if (buf[i] == '\n')
			nrecs++;
	}
	if (buf[len - 1] != '\n')
		nrecs++;

	struct record *records = malloc(nrecs * sizeof(*records));
	if (!records) {
		free(buf);
		fprintf(stderr, "c_sort: out of memory\n");
		return 2;
	}

	/* Fill the record array by scanning for newlines. */
	size_t ri = 0;
	size_t start = 0;
	for (size_t i = 0; i < len; i++) {
		if (buf[i] == '\n') {
			records[ri].ptr = buf + start;
			records[ri].len = i - start;
			ri++;
			start = i + 1;
		}
	}
	if (buf[len - 1] != '\n') {
		records[ri].ptr = buf + start;
		records[ri].len = len - start;
		ri++;
	}

	/* Sort unsigned bytewise ascending. */
	qsort(records, nrecs, sizeof(*records), cmp_records);

	/* Write each record followed by a newline. */
	for (size_t i = 0; i < nrecs; i++) {
		if (records[i].len > 0) {
			if (fwrite(records[i].ptr, 1, records[i].len, stdout)
			    != records[i].len) {
				free(records);
				free(buf);
				fprintf(stderr, "c_sort: write error\n");
				return 2;
			}
		}
		if (fputc('\n', stdout) == EOF) {
			free(records);
			free(buf);
			fprintf(stderr, "c_sort: write error\n");
			return 2;
		}
	}
	if (fflush(stdout) != 0) {
		free(records);
		free(buf);
		fprintf(stderr, "c_sort: write error\n");
		return 2;
	}

	free(records);
	free(buf);
	return 0;
}
