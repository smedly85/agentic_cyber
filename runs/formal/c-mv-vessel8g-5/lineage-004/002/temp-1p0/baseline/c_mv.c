#define _POSIX_C_SOURCE 200809L

#include <dirent.h>
#include <errno.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

extern char *realpath(const char *path, char *resolved);

static int move_path(const char *src, const char *dst)
{
	return rename(src, dst);
}

static const char *path_basename(const char *path)
{
	const char *slash = strrchr(path, '/');
	if (slash == NULL)
		return path;
	if (slash[1] == '\0') {
		const char *prev = NULL;
		for (const char *p = slash - 1; p >= path; p--) {
			if (*p == '/') {
				prev = p;
				break;
			}
		}
		if (prev == NULL)
			return path;
		return prev + 1;
	}
	return slash + 1;
}

static char *path_join(const char *dir, const char *name)
{
	size_t dl = strlen(dir);
	size_t nl = strlen(name);
	int need_slash = (dl > 0 && dir[dl - 1] != '/');
	size_t total = dl + (size_t)need_slash + nl + 1;
	char *buf = malloc(total);
	if (buf == NULL)
		return NULL;
	memcpy(buf, dir, dl);
	size_t pos = dl;
	if (need_slash)
		buf[pos++] = '/';
	memcpy(buf + pos, name, nl + 1);
	return buf;
}

static int dir_nonempty(const char *path)
{
	DIR *d = opendir(path);
	if (d == NULL)
		return -1;
	struct dirent *e;
	int result = 0;
	while ((e = readdir(d)) != NULL) {
		if (strcmp(e->d_name, ".") != 0 && strcmp(e->d_name, "..") != 0) {
			result = 1;
			break;
		}
	}
	closedir(d);
	return result;
}

static int is_within(const char *ancestor, const char *path)
{
	size_t al = strlen(ancestor);
	if (strncmp(ancestor, path, al) != 0)
		return 0;
	if (path[al] == '\0')
		return 1;
	if (path[al] == '/')
		return 1;
	return 0;
}

static char *canonicalize_path(const char *path)
{
	char buf[PATH_MAX];
	if (realpath(path, buf) != NULL)
		return strdup(buf);
	char *copy = strdup(path);
	if (copy == NULL)
		return NULL;
	char *slash = strrchr(copy, '/');
	if (slash != NULL && slash != copy) {
		*slash = '\0';
		if (realpath(copy, buf) != NULL) {
			char *result = strdup(buf);
			free(copy);
			return result;
		}
	}
	free(copy);
	return NULL;
}

int main(int argc, char **argv)
{
	size_t max_ops = (argc > 1) ? (size_t)(argc - 1) : 1;
	const char **operands = malloc(max_ops * sizeof(*operands));
	if (operands == NULL) {
		fprintf(stderr, "c_mv: out of memory\n");
		return 1;
	}
	int nops = 0;
	int after_ddash = 0;
	int force = 0;

	for (int i = 1; i < argc; i++) {
		const char *arg = argv[i];
		if (!after_ddash) {
			if (strcmp(arg, "--") == 0) {
				after_ddash = 1;
				continue;
			}
			if (arg[0] == '-' && arg[1] != '\0') {
				if (strcmp(arg, "-f") == 0 || strcmp(arg, "--force") == 0) {
					force = 1;
					continue;
				}
				fprintf(stderr, "c_mv: unrecognized option: %s\n", arg);
				free(operands);
				return 1;
			}
		}
		operands[nops++] = arg;
	}

	(void)force;

	if (nops < 2) {
		fprintf(stderr, "c_mv: missing destination operand\n");
		free(operands);
		return 1;
	}

	int nsrc = nops - 1;

	if (nops > 2) {
		const char *last = operands[nops - 1];
		struct stat st;
		if (stat(last, &st) != 0 || !S_ISDIR(st.st_mode)) {
			fprintf(stderr, "c_mv: %s: not a directory\n", last);
			free(operands);
			return 1;
		}
	}

	char **eff_dest = malloc((size_t)nsrc * sizeof(*eff_dest));
	if (eff_dest == NULL) {
		fprintf(stderr, "c_mv: out of memory\n");
		free(operands);
		return 1;
	}

	int any_move_failed = 0;

	for (int i = 0; i < nsrc; i++) {
		const char *src = operands[i];

		if (nops == 2) {
			const char *dst = operands[1];
			struct stat st;
			if (stat(dst, &st) == 0 && S_ISDIR(st.st_mode))
				eff_dest[i] = path_join(dst, path_basename(src));
			else
				eff_dest[i] = strdup(dst);
		} else {
			const char *dd = operands[nops - 1];
			eff_dest[i] = path_join(dd, path_basename(src));
		}

		if (eff_dest[i] == NULL) {
			fprintf(stderr, "c_mv: out of memory\n");
			any_move_failed = 1;
			continue;
		}

		struct stat ss;
		if (lstat(src, &ss) != 0) {
			fprintf(stderr, "c_mv: %s: %s\n", src, strerror(errno));
			any_move_failed = 1;
			free(eff_dest[i]);
			eff_dest[i] = NULL;
			continue;
		}

		if (strcmp(src, eff_dest[i]) == 0) {
			fprintf(stderr, "c_mv: %s: source and destination are identical\n", src);
			any_move_failed = 1;
			free(eff_dest[i]);
			eff_dest[i] = NULL;
			continue;
		}

		{
			struct stat a, b;
			if (stat(src, &a) == 0 && stat(eff_dest[i], &b) == 0) {
				if (a.st_dev == b.st_dev && a.st_ino == b.st_ino) {
					fprintf(stderr, "c_mv: %s: source and destination are identical\n", src);
					any_move_failed = 1;
					free(eff_dest[i]);
					eff_dest[i] = NULL;
					continue;
				}
			}
		}

		struct stat ds;
		if (lstat(eff_dest[i], &ds) == 0) {
			if (S_ISDIR(ss.st_mode) && !S_ISDIR(ds.st_mode)) {
				fprintf(stderr, "c_mv: cannot move directory %s to non-directory %s\n", src, eff_dest[i]);
				any_move_failed = 1;
				free(eff_dest[i]);
				eff_dest[i] = NULL;
				continue;
			}
			if (!S_ISDIR(ss.st_mode) && S_ISDIR(ds.st_mode)) {
				fprintf(stderr, "c_mv: cannot move non-directory %s to directory %s\n", src, eff_dest[i]);
				any_move_failed = 1;
				free(eff_dest[i]);
				eff_dest[i] = NULL;
				continue;
			}
			if (S_ISDIR(ss.st_mode) && S_ISDIR(ds.st_mode)) {
				int ne = dir_nonempty(eff_dest[i]);
				if (ne > 0) {
					fprintf(stderr, "c_mv: cannot move directory %s into non-empty directory %s\n", src, eff_dest[i]);
					any_move_failed = 1;
					free(eff_dest[i]);
					eff_dest[i] = NULL;
					continue;
				}
			}
		}

		if (S_ISDIR(ss.st_mode)) {
			char *src_canon = canonicalize_path(src);
			char *dst_canon = canonicalize_path(eff_dest[i]);
			if (src_canon != NULL && dst_canon != NULL) {
				if (is_within(src_canon, dst_canon)) {
					fprintf(stderr, "c_mv: cannot move directory %s into itself or its subdirectory\n", src);
					any_move_failed = 1;
					free(src_canon);
					free(dst_canon);
					free(eff_dest[i]);
					eff_dest[i] = NULL;
					continue;
				}
			}
			free(src_canon);
			free(dst_canon);
		}

		if (move_path(operands[i], eff_dest[i]) != 0) {
			fprintf(stderr, "c_mv: cannot move %s to %s: %s\n",
				operands[i], eff_dest[i], strerror(errno));
			any_move_failed = 1;
		}
		free(eff_dest[i]);
		eff_dest[i] = NULL;
	}

	free(eff_dest);
	free(operands);

	return any_move_failed ? 1 : 0;
}
