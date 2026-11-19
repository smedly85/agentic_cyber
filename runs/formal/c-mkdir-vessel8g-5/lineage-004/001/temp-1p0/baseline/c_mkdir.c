#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>

int main(int argc, char *argv[])
{
	const char *prog = "mkdir";
	int i;
	int saw_ddash = 0;
	int operand_count = 0;
	int any_error = 0;

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

		if (mkdir(operand, 0777) != 0) {
			int e = errno;
			fprintf(stderr, "%s: cannot create directory '%s': %s\n",
				prog, operand, strerror(e));
			any_error = 1;
		}
	}

	return any_error ? 1 : 0;
}
