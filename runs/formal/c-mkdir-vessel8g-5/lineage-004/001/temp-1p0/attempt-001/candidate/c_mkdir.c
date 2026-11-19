#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

static int mkdir_one(const char *path)
{
	if (mkdir(path, 0777) == 0)
		return 0;
	int e = errno;
	if (e == EEXIST) {
		struct stat st;
		if (stat(path, &st) == 0 && S_ISDIR(st.st_mode))
			return 0;
		errno = ENOTDIR;
	}
	return -1;
}

static int mkdir_intermediate(const char *path)
{
	if (mkdir(path, 0777) == 0) {
		struct stat st;
		if (stat(path, &st) == 0) {
			mode_t m = st.st_mode & 07777;
			if ((m & 0201) != 0201)
				(void)chmod(path, m | 0201);
		}
		return 0;
	}
	int e = errno;
	if (e == EEXIST) {
		struct stat st;
		if (stat(path, &st) == 0 && S_ISDIR(st.st_mode))
			return 0;
		errno = ENOTDIR;
	}
	return -1;
}

static int mkdir_parents(const char *operand)
{
	size_t len = strlen(operand);

	for (size_t i = 0; i < len; i++) {
		if (operand[i] != '/')
			continue;
		if (i == 0)
			continue;
		if (i == 1 && operand[0] == '/')
			continue;

		int has_content = 0;
		for (size_t j = i + 1; j < len; j++) {
			if (operand[j] != '/') {
				has_content = 1;
				break;
			}
		}
		if (!has_content)
			continue;

		char *prefix = malloc(i + 1);
		if (!prefix) {
			errno = ENOMEM;
			return -1;
		}
		memcpy(prefix, operand, i);
		prefix[i] = '\0';

		int rc = mkdir_intermediate(prefix);
		free(prefix);
		if (rc != 0)
			return -1;
	}

	return mkdir_one(operand);
}

int main(int argc, char *argv[])
{
	const char *prog = "mkdir";
	int i;
	int saw_ddash = 0;
	int operand_count = 0;
	int any_error = 0;
	int parents = 0;

	for (i = 1; i < argc; i++) {
		if (saw_ddash) {
			operand_count++;
			continue;
		}
		if (strcmp(argv[i], "--") == 0) {
			saw_ddash = 1;
			continue;
		}
		if (argv[i][0] == '-') {
			if (strcmp(argv[i], "-") == 0) {
				operand_count++;
			} else if (strcmp(argv[i], "-p") == 0) {
				parents = 1;
			} else if (strcmp(argv[i], "--parents") == 0) {
				parents = 1;
			} else if (argv[i][1] == '-' && argv[i][2] != '\0') {
				fprintf(stderr, "%s: unrecognized option '%s'\n", prog, argv[i]);
				fprintf(stderr, "Try '%s --help' for more information.\n", prog);
				return 1;
			} else {
				fprintf(stderr, "%s: invalid option -- '%c'\n", prog, argv[i][1]);
				fprintf(stderr, "Try '%s --help' for more information.\n", prog);
				return 1;
			}
		} else {
			operand_count++;
		}
	}

	if (operand_count == 0) {
		fprintf(stderr, "%s: missing operand\n", prog);
		fprintf(stderr, "Try '%s --help' for more information.\n", prog);
		return 1;
	}

	saw_ddash = 0;
	for (i = 1; i < argc; i++) {
		const char *operand;
		if (saw_ddash) {
			operand = argv[i];
		} else if (strcmp(argv[i], "--") == 0) {
			saw_ddash = 1;
			continue;
		} else if (argv[i][0] == '-') {
			if (strcmp(argv[i], "-") == 0)
				operand = argv[i];
			else
				continue;
		} else {
			operand = argv[i];
		}

		if (parents) {
			if (mkdir_parents(operand) != 0) {
				fprintf(stderr, "%s: cannot create directory '%s': %s\n",
					prog, operand, strerror(errno));
				any_error = 1;
			}
		} else {
			if (mkdir(operand, 0777) != 0) {
				fprintf(stderr, "%s: cannot create directory '%s': %s\n",
					prog, operand, strerror(errno));
				any_error = 1;
			}
		}
	}

	return any_error ? 1 : 0;
}
