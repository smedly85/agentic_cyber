#include <errno.h>
#include <dirent.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

static int cmp_entry_names(const void *a, const void *b)
{
	const char *sa = *(const char * const *)a;
	const char *sb = *(const char * const *)b;
	size_t i = 0;
	while (sa[i] != '\0' && sb[i] != '\0' && sa[i] == sb[i])
		i++;
	return (int)(unsigned char)sa[i] - (int)(unsigned char)sb[i];
}

static unsigned char fold_byte(unsigned char c)
{
	if (c >= 'A' && c <= 'Z')
		return c - 'A' + 'a';
	return c;
}

static char *join_path(const char *base, const char *suffix)
{
	size_t base_len = strlen(base);
	size_t suffix_len = strlen(suffix);
	int need_slash = (base_len > 0 && base[base_len - 1] != '/');
	size_t total = base_len + (need_slash ? 1 : 0) + suffix_len + 1;
	char *result = malloc(total);
	if (!result)
		return NULL;
	memcpy(result, base, base_len);
	size_t pos = base_len;
	if (need_slash)
		result[pos++] = '/';
	memcpy(result + pos, suffix, suffix_len + 1);
	return result;
}

int search_stream(FILE *fp, const unsigned char *pattern, size_t pattern_len,
                  const unsigned char *prefix, size_t prefix_len, int *found,
                  int ignore_case);

static void search_one_file(const char *path,
			    const unsigned char *pattern, size_t pattern_len,
			    int prefix_enabled, int *found, int *had_error,
			    int ignore_case);

static void traverse_dir(const char *dir_path,
			 const unsigned char *pattern, size_t pattern_len,
			 int prefix_enabled, int *found, int *had_error,
			 int ignore_case);

static int line_contains(const unsigned char *hay, size_t hay_len,
                         const unsigned char *needle, size_t needle_len,
                         int ignore_case)
{
	if (needle_len == 0)
		return 1;
	if (needle_len > hay_len)
		return 0;
	for (size_t i = 0; i <= hay_len - needle_len; i++) {
		int match = 1;
		for (size_t j = 0; j < needle_len; j++) {
			unsigned char h = ignore_case ? fold_byte(hay[i + j]) : hay[i + j];
			unsigned char n = ignore_case ? fold_byte(needle[j]) : needle[j];
			if (h != n) {
				match = 0;
				break;
			}
		}
		if (match)
			return 1;
	}
	return 0;
}

int search_stream(FILE *fp, const unsigned char *pattern, size_t pattern_len,
                  const unsigned char *prefix, size_t prefix_len, int *found,
                  int ignore_case)
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
			if (line_contains(line, line_len, pattern, pattern_len, ignore_case)) {
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
		if (line_contains(line, line_len, pattern, pattern_len, ignore_case)) {
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

static void search_one_file(const char *path,
			    const unsigned char *pattern, size_t pattern_len,
			    int prefix_enabled, int *found, int *had_error,
			    int ignore_case)
{
	struct stat st;
	if (stat(path, &st) != 0) {
		fprintf(stderr, "c_grep: %s: %s\n", path, strerror(errno));
		*had_error = 1;
		return;
	}
	if (S_ISDIR(st.st_mode)) {
		fprintf(stderr, "c_grep: %s: Is a directory\n", path);
		*had_error = 1;
		return;
	}

	FILE *fp = fopen(path, "rb");
	if (!fp) {
		fprintf(stderr, "c_grep: %s: %s\n", path, strerror(errno));
		*had_error = 1;
		return;
	}

	unsigned char *prefix_buf = NULL;
	size_t prefix_len = 0;
	if (prefix_enabled) {
		size_t fn_len = strlen(path);
		prefix_buf = malloc(fn_len + 1);
		if (!prefix_buf) {
			fclose(fp);
			*had_error = 1;
			return;
		}
		memcpy(prefix_buf, path, fn_len);
		prefix_buf[fn_len] = ':';
		prefix_len = fn_len + 1;
	}

	int local_found = 0;
	int rc = search_stream(fp, pattern, pattern_len,
			       prefix_buf, prefix_len, &local_found, ignore_case);
	if (local_found)
		*found = 1;
	if (rc == -1)
		*had_error = 1;

	free(prefix_buf);
	fclose(fp);
}

static void traverse_dir(const char *dir_path,
			 const unsigned char *pattern, size_t pattern_len,
			 int prefix_enabled, int *found, int *had_error,
			 int ignore_case)
{
	DIR *dp = opendir(dir_path);
	if (!dp) {
		fprintf(stderr, "c_grep: %s: %s\n", dir_path, strerror(errno));
		*had_error = 1;
		return;
	}

	char **names = NULL;
	size_t count = 0, cap = 0;
	struct dirent *de;
	while ((de = readdir(dp)) != NULL) {
		if (strcmp(de->d_name, ".") == 0 || strcmp(de->d_name, "..") == 0)
			continue;
		if (count >= cap) {
			size_t new_cap = cap == 0 ? 32 : cap * 2;
			char **tmp = realloc(names, new_cap * sizeof(*tmp));
			if (!tmp) {
				for (size_t i = 0; i < count; i++)
					free(names[i]);
				free(names);
				closedir(dp);
				*had_error = 1;
				return;
			}
			names = tmp;
			cap = new_cap;
		}
		size_t nlen = strlen(de->d_name);
		char *copy = malloc(nlen + 1);
		if (!copy) {
			for (size_t i = 0; i < count; i++)
				free(names[i]);
			free(names);
			closedir(dp);
			*had_error = 1;
			return;
		}
		memcpy(copy, de->d_name, nlen + 1);
		names[count++] = copy;
	}
	closedir(dp);

	if (count > 0)
		qsort(names, count, sizeof(*names), cmp_entry_names);

	for (size_t i = 0; i < count; i++) {
		char *full = join_path(dir_path, names[i]);
		if (!full) {
			*had_error = 1;
			for (size_t k = 0; k < count; k++)
				free(names[k]);
			free(names);
			return;
		}

		struct stat lst;
		if (lstat(full, &lst) != 0) {
			fprintf(stderr, "c_grep: %s: %s\n", full, strerror(errno));
			*had_error = 1;
			free(full);
			continue;
		}

		if (S_ISLNK(lst.st_mode)) {
			free(full);
			continue;
		} else if (S_ISREG(lst.st_mode)) {
			search_one_file(full, pattern, pattern_len,
					prefix_enabled, found, had_error, ignore_case);
			free(full);
		} else if (S_ISDIR(lst.st_mode)) {
			traverse_dir(full, pattern, pattern_len,
				     prefix_enabled, found, had_error, ignore_case);
			free(full);
		} else {
			free(full);
		}
	}

	for (size_t i = 0; i < count; i++)
		free(names[i]);
	free(names);
}

int main(int argc, char *argv[])
{
	int filename_mode = 0;  /* 0=unset, 1=force(-H), -1=suppress(-h) */
	int recursive = 0;
	int ignore_case = 0;
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
				filename_mode = 1;
				continue;
			}
			if (strcmp(arg, "--no-filename") == 0) {
				filename_mode = -1;
				continue;
			}
			if (strcmp(arg, "--recursive") == 0) {
				recursive = 1;
				continue;
			}
			if (strcmp(arg, "--ignore-case") == 0) {
				ignore_case = 1;
				continue;
			}
			size_t len = strlen(arg);
			int valid = 1;
			for (size_t k = 1; k < len; k++) {
				if (arg[k] != 'H' && arg[k] != 'h' && arg[k] != 'r' && arg[k] != 'i') {
					valid = 0;
					break;
				}
			}
			if (valid) {
				for (size_t k = 1; k < len; k++) {
					if (arg[k] == 'H')
						filename_mode = 1;
					else if (arg[k] == 'h')
						filename_mode = -1;
					else if (arg[k] == 'r')
						recursive = 1;
					else if (arg[k] == 'i')
						ignore_case = 1;
				}
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
	int any_dir = 0;
	if (nfiles > 0 && recursive) {
		for (int j = 0; j < nfiles; j++) {
			struct stat st;
			if (stat(argv[file_start + j], &st) == 0 && S_ISDIR(st.st_mode))
				any_dir = 1;
		}
	}
	int multi = (nfiles >= 2) || any_dir;
	int found = 0;
	int had_error = 0;

	if (nfiles == 0) {
		const unsigned char *prefix = NULL;
		size_t prefix_len = 0;
		if (filename_mode == 1) {
			static const char stdin_name[] = "(standard input):";
			prefix = (const unsigned char *)stdin_name;
			prefix_len = sizeof(stdin_name) - 1;
		}
		int local_found = 0;
		int rc = search_stream(stdin, pattern, pattern_len,
		                       prefix, prefix_len, &local_found, ignore_case);
		if (local_found)
			found = 1;
		if (rc == -1)
			had_error = 1;
	} else {
		int prefix_enabled = (filename_mode == 1) ||
			(filename_mode == 0 && multi);

		for (int j = 0; j < nfiles; j++) {
			const char *filename = argv[file_start + j];

			struct stat st;
			if (stat(filename, &st) != 0) {
				fprintf(stderr, "c_grep: %s: %s\n", filename, strerror(errno));
				had_error = 1;
				continue;
			}

			if (S_ISDIR(st.st_mode)) {
				if (!recursive) {
					fprintf(stderr, "c_grep: %s: Is a directory\n", filename);
					had_error = 1;
					continue;
				}
				traverse_dir(filename, pattern, pattern_len,
					     prefix_enabled, &found, &had_error, ignore_case);
			} else {
				search_one_file(filename, pattern, pattern_len,
						prefix_enabled, &found, &had_error, ignore_case);
			}
		}
	}

	if (had_error)
		return 2;
	return found ? 0 : 1;
}
