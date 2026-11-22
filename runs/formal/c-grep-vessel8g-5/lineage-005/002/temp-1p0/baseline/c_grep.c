#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

static int line_contains(const unsigned char *hay, size_t hay_len,
                         const unsigned char *needle, size_t needle_len)
{
	if (needle_len == 0)
		return 1;
	if (needle_len > hay_len)
		return 0;
	for (size_t i = 0; i <= hay_len - needle_len; i++) {
		if (memcmp(hay + i, needle, needle_len) == 0)
			return 1;
	}
	return 0;
}

int search_stream(FILE *fp, const unsigned char *pattern, size_t pattern_len,
                  const unsigned char *prefix, size_t prefix_len, int *found)
{
	unsigned char *line = NULL;
	size_t line_len = 0, line_cap = 0;
	int error = 0;

	for (;;) {
		int c = fgetc(fp);
		if (c == EOF) {
			if (ferror(fp))
				error = 1;
			break;
		}
		if ((unsigned char)c == '\n') {
			if (line_contains(line, line_len, pattern, pattern_len)) {
				if (prefix_len && fwrite(prefix, 1, prefix_len, stdout) != prefix_len)
					error = 1;
				if (line_len && fwrite(line, 1, line_len, stdout) != line_len)
					error = 1;
				if (fputc('\n', stdout) == EOF)
					error = 1;
				*found = 1;
			}
			line_len = 0;
		} else {
			if (line_len + 1 > line_cap) {
				size_t new_cap;
				if (line_cap == 0)
					new_cap = 8192;
				else if (line_cap > (SIZE_MAX - 1) / 2) {
					free(line);
					return -1;
				} else
					new_cap = line_cap * 2;
				unsigned char *tmp = realloc(line, new_cap);
				if (!tmp) {
					free(line);
					return -1;
				}
				line = tmp;
				line_cap = new_cap;
			}
			line[line_len++] = (unsigned char)c;
		}
	}

	/* Final unterminated line */
	if (line_len > 0) {
		if (line_contains(line, line_len, pattern, pattern_len)) {
			if (prefix_len && fwrite(prefix, 1, prefix_len, stdout) != prefix_len)
				error = 1;
			if (fwrite(line, 1, line_len, stdout) != line_len)
				error = 1;
			if (fputc('\n', stdout) == EOF)
				error = 1;
			*found = 1;
		}
	}

	free(line);
	return error ? -1 : 0;
}

int main(int argc, char *argv[])
{
	int want_filename = 0;
	int i = 1;
	int pattern_set = 0;
	int pattern_idx = -1;
	int file_start = -1;
	int end_options = 0;

	for (; i < argc; i++) {
		if (end_options) {
			if (!pattern_set) {
				pattern_set = 1;
				pattern_idx = i;
			} else if (file_start == -1) {
				file_start = i;
			}
			continue;
		}

		const char *arg = argv[i];

		if (strcmp(arg, "--") == 0) {
			end_options = 1;
			continue;
		}

		if (arg[0] == '-' && arg[1] != '\0') {
			if (strcmp(arg, "--with-filename") == 0) {
				want_filename = 1;
				continue;
			}
			size_t len = strlen(arg);
			int valid = 1;
			for (size_t k = 1; k < len; k++) {
				if (arg[k] != 'H') {
					valid = 0;
					break;
				}
			}
			if (valid) {
				want_filename = 1;
				continue;
			}
			fprintf(stderr, "c_grep: unsupported option '%s'\n", arg);
			return 2;
		}

		if (!pattern_set) {
			pattern_set = 1;
			pattern_idx = i;
		} else if (file_start == -1) {
			file_start = i;
		}
	}

	if (!pattern_set) {
		fprintf(stderr, "c_grep: missing PATTERN\n");
		return 2;
	}

	const unsigned char *pattern = (const unsigned char *)argv[pattern_idx];
	size_t pattern_len = strlen(argv[pattern_idx]);

	int nfiles = (file_start == -1) ? 0 : argc - file_start;
	int multi = (nfiles >= 2);
	int found = 0;
	int had_error = 0;

	if (nfiles == 0) {
		const unsigned char *prefix = NULL;
		size_t prefix_len = 0;
		if (want_filename) {
			static const char stdin_name[] = "(standard input):";
			prefix = (const unsigned char *)stdin_name;
			prefix_len = sizeof(stdin_name) - 1;
		}
		int local_found = 0;
		int rc = search_stream(stdin, pattern, pattern_len,
		                       prefix, prefix_len, &local_found);
		if (local_found)
			found = 1;
		if (rc == -1)
			had_error = 1;
	} else {
		for (int j = 0; j < nfiles; j++) {
			const char *filename = argv[file_start + j];

			struct stat st;
			if (stat(filename, &st) == 0 && S_ISDIR(st.st_mode)) {
				fprintf(stderr, "c_grep: %s: Is a directory\n", filename);
				had_error = 1;
				continue;
			}

			FILE *fp = fopen(filename, "rb");
			if (!fp) {
				fprintf(stderr, "c_grep: %s: %s\n", filename, strerror(errno));
				had_error = 1;
				continue;
			}

			unsigned char *prefix_buf = NULL;
			size_t prefix_len = 0;
			if (want_filename || multi) {
				size_t fn_len = strlen(filename);
				prefix_buf = malloc(fn_len + 1);
				if (!prefix_buf) {
					fclose(fp);
					had_error = 1;
					continue;
				}
				memcpy(prefix_buf, filename, fn_len);
				prefix_buf[fn_len] = ':';
				prefix_len = fn_len + 1;
			}

			int local_found = 0;
			int rc = search_stream(fp, pattern, pattern_len,
			                       prefix_buf, prefix_len, &local_found);
			if (local_found)
				found = 1;
			if (rc == -1)
				had_error = 1;

			free(prefix_buf);
			fclose(fp);
		}
	}

	if (had_error)
		return 2;
	return found ? 0 : 1;
}
