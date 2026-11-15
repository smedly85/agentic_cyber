#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

static int force_flag = 0;
static int interactive_flag = 0;

static const char *base_name(const char *path)
{
	const char *slash = strrchr(path, '/');
	return slash ? slash + 1 : path;
}

static int interactive_prompt(const char *dest)
{
	char buf[256];
	fprintf(stderr, "cp: overwrite '%s'? ", dest);
	if (!fgets(buf, sizeof(buf), stdin))
		return 0;
	return (buf[0] == 'y' || buf[0] == 'Y') ? 1 : 0;
}

static int copy_path(const char *src, const char *dest)
{
	struct stat src_stat, dest_stat;
	int src_fd, dest_fd;
	char buf[65536];
	ssize_t nread, nwritten;
	int dest_existed = 0;

	if (stat(src, &src_stat) != 0) {
		fprintf(stderr, "cp: cannot stat '%s': %s\n", src, strerror(errno));
		return -1;
	}
	if (!S_ISREG(src_stat.st_mode)) {
		fprintf(stderr, "cp: '%s': not a regular file\n", src);
		return -1;
	}

	if (stat(dest, &dest_stat) == 0) {
		if (!S_ISREG(dest_stat.st_mode)) {
			fprintf(stderr, "cp: cannot create '%s': %s\n", dest,
				S_ISDIR(dest_stat.st_mode)
					? "Is a directory"
					: "Inappropriate file type");
			return -1;
		}
		if (src_stat.st_dev == dest_stat.st_dev &&
		    src_stat.st_ino == dest_stat.st_ino) {
			fprintf(stderr, "cp: '%s' and '%s' are the same file\n",
				src, dest);
			return -1;
		}
		dest_existed = 1;
	} else {
		struct stat ls;
		if (lstat(dest, &ls) == 0 && S_ISLNK(ls.st_mode)) {
			fprintf(stderr,
				"cp: cannot create '%s': No such file or directory\n",
				dest);
			return -1;
		}
	}

	if (dest_existed && interactive_flag) {
		if (!interactive_prompt(dest))
			return 1;
	}

	src_fd = open(src, O_RDONLY);
	if (src_fd < 0) {
		fprintf(stderr, "cp: cannot open '%s' for reading: %s\n",
			src, strerror(errno));
		return -1;
	}

	if (dest_existed) {
		dest_fd = open(dest, O_WRONLY | O_TRUNC);
		if (dest_fd < 0 && force_flag) {
			struct stat ds;
			if (stat(dest, &ds) == 0 && !S_ISDIR(ds.st_mode) &&
			    unlink(dest) == 0) {
				dest_fd = open(dest, O_WRONLY | O_CREAT | O_TRUNC,
					       (mode_t)(src_stat.st_mode & 07777));
			}
		}
	} else {
		dest_fd = open(dest, O_WRONLY | O_CREAT | O_TRUNC,
			       (mode_t)(src_stat.st_mode & 07777));
	}
	if (dest_fd < 0) {
		fprintf(stderr, "cp: cannot create '%s': %s\n", dest,
			strerror(errno));
		close(src_fd);
		return -1;
	}

	for (;;) {
		nread = read(src_fd, buf, sizeof(buf));
		if (nread < 0) {
			fprintf(stderr, "cp: error reading '%s': %s\n",
				src, strerror(errno));
			goto fail;
		}
		if (nread == 0)
			break;
		nwritten = 0;
		while (nwritten < nread) {
			ssize_t w = write(dest_fd, buf + nwritten,
					 nread - nwritten);
			if (w < 0) {
				fprintf(stderr, "cp: error writing '%s': %s\n",
					dest, strerror(errno));
				goto fail;
			}
			nwritten += w;
		}
	}

	close(src_fd);
	close(dest_fd);
	return 0;

fail:
	close(src_fd);
	close(dest_fd);
	return -1;
}

int main(int argc, char *argv[])
{
	int i, sep_idx = -1, n_operands = 0, n_ops = 0;
	char **operands;
	int failed = 0;
	int last_is_dir = 0;
	const char *dir_arg = NULL;
	int n_sources;

	for (i = 1; i < argc; i++) {
		if (strcmp(argv[i], "--") == 0) {
			sep_idx = i;
			break;
		}
	}

	for (i = 1; i < argc; i++) {
		if (i == sep_idx)
			break;
		if (strcmp(argv[i], "-f") == 0 || strcmp(argv[i], "--force") == 0) {
			force_flag = 1;
		} else if (strcmp(argv[i], "-i") == 0 ||
			   strcmp(argv[i], "--interactive") == 0) {
			interactive_flag = 1;
		} else if (argv[i][0] == '-' && argv[i][1] != '\0') {
			fprintf(stderr, "cp: unknown option '%s'\n", argv[i]);
			return 1;
		}
	}

	for (i = 1; i < argc; i++) {
		if (i == sep_idx)
			continue;
		if (sep_idx < 0 || i < sep_idx) {
			if (strcmp(argv[i], "-f") == 0 ||
			    strcmp(argv[i], "--force") == 0 ||
			    strcmp(argv[i], "-i") == 0 ||
			    strcmp(argv[i], "--interactive") == 0)
				continue;
		}
		n_operands++;
	}

	if (n_operands < 2) {
		fprintf(stderr, "cp: missing operand\n");
		return 1;
	}

	operands = malloc((size_t)n_operands * sizeof(char *));
	if (!operands) {
		fprintf(stderr, "cp: out of memory\n");
		return 1;
	}

	for (i = 1; i < argc; i++) {
		if (i == sep_idx)
			continue;
		if (sep_idx < 0 || i < sep_idx) {
			if (strcmp(argv[i], "-f") == 0 ||
			    strcmp(argv[i], "--force") == 0 ||
			    strcmp(argv[i], "-i") == 0 ||
			    strcmp(argv[i], "--interactive") == 0)
				continue;
		}
		operands[n_ops++] = argv[i];
	}

	if (n_operands >= 3) {
		struct stat st;
		const char *last = operands[n_operands - 1];
		if (stat(last, &st) != 0) {
			fprintf(stderr,
				"cp: target '%s': No such file or directory\n",
				last);
			free(operands);
			return 1;
		}
		if (!S_ISDIR(st.st_mode)) {
			fprintf(stderr,
				"cp: target '%s': Not a directory\n", last);
			free(operands);
			return 1;
		}
		last_is_dir = 1;
		dir_arg = last;
	}

	n_sources = n_operands - 1;

	for (i = 0; i < n_sources; i++) {
		const char *src = operands[i];
		char dest[4096];
		int n;

		if (last_is_dir) {
			const char *bn = base_name(src);
			size_t dl = strlen(dir_arg);
			if (dl > 0 && dir_arg[dl - 1] == '/')
				n = snprintf(dest, sizeof(dest), "%s%s",
					     dir_arg, bn);
			else
				n = snprintf(dest, sizeof(dest), "%s/%s",
					     dir_arg, bn);
			if (n < 0 || (size_t)n >= sizeof(dest)) {
				fprintf(stderr, "cp: path too long\n");
				failed = 1;
				continue;
			}
		} else {
			struct stat dst;
			if (stat(operands[1], &dst) == 0 &&
			    S_ISDIR(dst.st_mode)) {
				const char *bn = base_name(src);
				size_t dl = strlen(operands[1]);
				if (dl > 0 && operands[1][dl - 1] == '/')
					n = snprintf(dest, sizeof(dest),
						      "%s%s", operands[1], bn);
				else
					n = snprintf(dest, sizeof(dest),
						      "%s/%s", operands[1], bn);
			} else {
				n = snprintf(dest, sizeof(dest), "%s",
					     operands[1]);
			}
			if (n < 0 || (size_t)n >= sizeof(dest)) {
				fprintf(stderr, "cp: path too long\n");
				failed = 1;
				continue;
			}
		}

		if (copy_path(src, dest) != 0)
			failed = 1;
	}

	free(operands);
	return failed ? 1 : 0;
}
