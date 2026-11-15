#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

/* Core filesystem move: the semantic anchor required by the specification. */
static int move_path(const char *src, const char *dst)
{
	return rename(src, dst);
}

/* Return a pointer to the last path component (after the final '/'). */
static const char *base_of(const char *path)
{
	const char *s = strrchr(path, '/');
	return s ? s + 1 : path;
}

/* Lexically normalize a path: resolve '.' and '..' components.
 * Returns a malloc'd string, or NULL on allocation failure. */
static char *normalize_path(const char *path)
{
	size_t len = strlen(path);
	char *result = malloc(len + 1);
	if (!result) return NULL;

	int is_abs = (path[0] == '/');
	size_t out_pos = 0;

	const char *components[256];
	size_t comp_lens[256];
	int depth = 0;

	const char *p = path;
	while (*p) {
		while (*p == '/') p++;
		if (!*p) break;
		const char *start = p;
		while (*p && *p != '/') p++;
		size_t clen = (size_t)(p - start);

		if (clen == 1 && start[0] == '.') {
			continue;
		} else if (clen == 2 && start[0] == '.' && start[1] == '.') {
			if (depth > 0) depth--;
		} else {
			if (depth >= 256) { free(result); return NULL; }
			components[depth] = start;
			comp_lens[depth] = clen;
			depth++;
		}
	}

	if (is_abs) result[out_pos++] = '/';
	for (int i = 0; i < depth; i++) {
		if (i > 0) result[out_pos++] = '/';
		memcpy(result + out_pos, components[i], comp_lens[i]);
		out_pos += comp_lens[i];
	}
	result[out_pos] = '\0';
	return result;
}

int main(int argc, char *argv[])
{
	const char **ops = malloc((size_t)argc * sizeof *ops);
	if (!ops) {
		fprintf(stderr, "mv: out of memory\n");
		return 1;
	}
	int nops = 0;
	int seen_ddash = 0;

	for (int i = 1; i < argc; i++) {
		if (!seen_ddash) {
			if (strcmp(argv[i], "--") == 0) {
				seen_ddash = 1;
				continue;
			}
			if (argv[i][0] == '-' && argv[i][1] != '\0') {
				fprintf(stderr, "mv: invalid option -- '%c'\n", argv[i][1]);
				free(ops);
				return 1;
			}
		}
		ops[nops++] = argv[i];
	}

	if (nops < 2) {
		fprintf(stderr, "mv: missing destination file operand\n");
		free(ops);
		return 1;
	}

	const char *dest = ops[nops - 1];
	int nsrc = nops - 1;

	/* Multiple sources require the destination to be an existing directory. */
	if (nsrc > 1) {
		struct stat st;
		if (stat(dest, &st) != 0 || !S_ISDIR(st.st_mode)) {
			fprintf(stderr, "mv: target '%s': Not a directory\n", dest);
			free(ops);
			return 1;
		}
	}

	int any_fail = 0;

	for (int i = 0; i < nsrc; i++) {
		const char *src = ops[i];
		struct stat sst;
		if (lstat(src, &sst) != 0) {
			fprintf(stderr, "mv: cannot stat '%s': %s\n", src, strerror(errno));
			any_fail = 1;
			continue;
		}
		int src_is_dir = S_ISDIR(sst.st_mode);

		/* Determine whether the destination is a directory. */
		int dest_is_dir = (nsrc > 1);
		if (nsrc == 1) {
			struct stat dst;
			if (stat(dest, &dst) == 0 && S_ISDIR(dst.st_mode))
				dest_is_dir = 1;
		}

		/* Compute the effective destination path. */
		char *eff = NULL;
		if (dest_is_dir) {
			size_t dl = strlen(dest);
			while (dl > 1 && dest[dl - 1] == '/')
				dl--;
			const char *bn = base_of(src);
			size_t bl = strlen(bn);
			eff = malloc(dl + 1 + bl + 1);
			if (!eff) {
				fprintf(stderr, "mv: out of memory\n");
				any_fail = 1;
				continue;
			}
			memcpy(eff, dest, dl);
			eff[dl] = '/';
			memcpy(eff + dl + 1, bn, bl);
			eff[dl + 1 + bl] = '\0';
		} else {
			eff = (char *)dest;
		}
		int eff_owned = (eff != (char *)dest);

		/* Identity check via inode comparison (lstat does not follow symlinks). */
		{
			struct stat ds;
			if (lstat(eff, &ds) == 0
			    && sst.st_dev == ds.st_dev && sst.st_ino == ds.st_ino) {
				fprintf(stderr, "mv: '%s' and '%s' are the same file\n", src, eff);
				if (eff_owned) free(eff);
				any_fail = 1;
				continue;
			}
		}

		/* Descendant check: a directory source must not be moved into itself. */
		if (src_is_dir) {
			char *ns = normalize_path(src);
			char *nd = normalize_path(eff);
			if (ns && nd) {
				size_t sl = strlen(ns);
				if (strncmp(nd, ns, sl) == 0 && nd[sl] == '/') {
					fprintf(stderr,
					      "mv: cannot move '%s' to a subdirectory of itself, '%s'\n",
					      src, eff);
					free(ns); free(nd);
					if (eff_owned) free(eff);
					any_fail = 1;
					continue;
				}
			}
			free(ns);
			free(nd);
		}

		/* Type compatibility at the effective destination. */
		{
			struct stat dst;
			if (stat(eff, &dst) == 0) {
				int d_is_dir = S_ISDIR(dst.st_mode);
				if (src_is_dir && !d_is_dir) {
					fprintf(stderr,
					      "mv: cannot move directory '%s' to non-directory '%s'\n",
					      src, eff);
					if (eff_owned) free(eff);
					any_fail = 1;
					continue;
				}
				if (!src_is_dir && d_is_dir) {
					fprintf(stderr,
					      "mv: cannot overwrite directory '%s' with non-directory '%s'\n",
					      eff, src);
					if (eff_owned) free(eff);
					any_fail = 1;
					continue;
				}
			}
		}

		/* Perform the move. */
		if (move_path(src, eff) != 0) {
			fprintf(stderr, "mv: cannot move '%s' to '%s': %s\n",
				src, eff, strerror(errno));
			if (eff_owned) free(eff);
			any_fail = 1;
			continue;
		}

		if (eff_owned) free(eff);
	}

	free(ops);
	return any_fail ? 1 : 0;
}
