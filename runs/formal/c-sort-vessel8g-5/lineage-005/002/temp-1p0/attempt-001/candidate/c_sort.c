#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

static int g_reverse;
static int g_ignore_case;

struct record {
    const unsigned char *ptr;
    size_t len;
};

static unsigned char fold_byte(unsigned char c)
{
	if (c >= 'A' && c <= 'Z')
		return (unsigned char)(c - 'A' + 'a');
	return c;
}

static int cmp_records(const void *a, const void *b)
{
	const struct record *ra = (const struct record *)a;
	const struct record *rb = (const struct record *)b;
	int result = 0;
	size_t minlen = ra->len < rb->len ? ra->len : rb->len;

	if (g_ignore_case) {
		for (size_t i = 0; i < minlen; i++) {
			unsigned char fa = fold_byte(ra->ptr[i]);
			unsigned char fb = fold_byte(rb->ptr[i]);
			if (fa != fb) {
				result = (int)fa - (int)fb;
				return g_reverse ? -result : result;
			}
		}
		if (ra->len != rb->len)
			result = (ra->len < rb->len) ? -1 : 1;
		else
			result = (int)memcmp(ra->ptr, rb->ptr, ra->len);
	} else {
		int c = (int)memcmp(ra->ptr, rb->ptr, minlen);
		if (c != 0)
			result = c;
		else if (ra->len < rb->len)
			result = -1;
		else if (ra->len > rb->len)
			result = 1;
	}

	if (g_reverse)
		result = -result;
	return result;
}

int main(int argc, char *argv[])
{
	int reverse = 0;
	int saw_ddash = 0;

	for (int i = 1; i < argc; i++) {
		if (saw_ddash) {
			fprintf(stderr, "sort: cannot read: %s: No such file or directory\n", argv[i]);
			return 2;
		}
		if (strcmp(argv[i], "--") == 0) {
			saw_ddash = 1;
			continue;
		}
		if (strcmp(argv[i], "--reverse") == 0) {
			reverse = 1;
			continue;
		}
		if (strcmp(argv[i], "--ignore-case") == 0) {
			g_ignore_case = 1;
			continue;
		}
		if (argv[i][0] == '-' && strlen(argv[i]) > 1) {
			if (argv[i][1] == '-') {
				fprintf(stderr, "sort: unrecognized option '%s'\nTry 'sort --help' for more information.\n", argv[i]);
				return 2;
			}
			for (size_t j = 1; j < strlen(argv[i]); j++) {
				if (argv[i][j] == 'r') {
					reverse = 1;
				} else if (argv[i][j] == 'f') {
					g_ignore_case = 1;
				} else {
					fprintf(stderr, "sort: unrecognized option '%s'\nTry 'sort --help' for more information.\n", argv[i]);
					return 2;
				}
			}
		} else if (strcmp(argv[i], "-") == 0) {
			fprintf(stderr, "sort: cannot read: %s: No such file or directory\n", argv[i]);
			return 2;
		} else {
			fprintf(stderr, "sort: cannot read: %s: No such file or directory\n", argv[i]);
			return 2;
		}
	}

	g_reverse = reverse;

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
