#define _POSIX_C_SOURCE 200809L
#include <dirent.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#define MAX_CLAUSES 64

typedef struct {
    int classes; /* bitmask: bit0=u, bit1=g, bit2=o; 0 means "all" */
    char op;     /* '+', '-', '=' */
    int perms;   /* bitmask: bit0=r, bit1=w, bit2=x, bit3=X */
} clause_t;

typedef struct {
    int is_octal;
    mode_t octal_value;
    clause_t clauses[MAX_CLAUSES];
    int n_clauses;
} mode_spec_t;

static void usage_exit(void) {
    fprintf(stderr, "usage: new_chmod MODE FILE...\n");
    exit(1);
}

static int parse_symbolic(const char *s, clause_t *clauses, int *n_clauses) {
    *n_clauses = 0;
    const char *p = s;

    for (;;) {
        const char *comma = strchr(p, ',');
        size_t len = comma ? (size_t)(comma - p) : strlen(p);

        if (len == 0)
            return -1;

        clause_t c;
        c.classes = 0;
        c.perms = 0;
        const char *q = p;

        /* class letters */
        while ((size_t)(q - p) < len) {
            char ch = *q;
            if (ch == 'u')      { c.classes |= 1; q++; }
            else if (ch == 'g') { c.classes |= 2; q++; }
            else if (ch == 'o') { c.classes |= 4; q++; }
            else if (ch == 'a') { c.classes |= 7; q++; }
            else break;
        }

        /* operator (must be present) */
        if ((size_t)(q - p) >= len)
            return -1;
        c.op = *q;
        if (c.op != '+' && c.op != '-' && c.op != '=')
            return -1;
        q++;

        /* permission letters */
        while ((size_t)(q - p) < len) {
            char ch = *q;
            if (ch == 'r')      { c.perms |= 1; q++; }
            else if (ch == 'w') { c.perms |= 2; q++; }
            else if (ch == 'x') { c.perms |= 4; q++; }
            else if (ch == 'X') { c.perms |= 8; q++; }
            else return -1;
        }

        if (*n_clauses >= MAX_CLAUSES)
            return -1;
        clauses[(*n_clauses)++] = c;

        if (!comma)
            break;
        p = comma + 1;
    }
    return 0;
}

static int parse_mode(const char *s, mode_spec_t *spec) {
    memset(spec, 0, sizeof(*spec));
    size_t len = strlen(s);
    if (len == 0)
        return -1;

    /* If all characters are ASCII digits, it must be octal */
    int all_digits = 1;
    for (size_t i = 0; i < len; i++) {
        if (s[i] < '0' || s[i] > '9') { all_digits = 0; break; }
    }

    if (all_digits) {
        if (len > 4)
            return -1;
        for (size_t i = 0; i < len; i++) {
            if (s[i] > '7')
                return -1;
        }
        spec->is_octal = 1;
        spec->octal_value = (mode_t)strtol(s, NULL, 8);
        return 0;
    }

    spec->is_octal = 0;
    return parse_symbolic(s, spec->clauses, &spec->n_clauses);
}

static mode_t apply_symbolic(mode_t current, const clause_t *clauses,
                             int n, int is_dir) {
    mode_t result = current;

    for (int i = 0; i < n; i++) {
        const clause_t *c = &clauses[i];
        int classes = c->classes;
        if (classes == 0)
            classes = 7; /* empty class list means all three */

        /* Build the permission bits mask across all three classes */
        int bits = 0;
        if (c->perms & 1) bits |= 0444; /* r */
        if (c->perms & 2) bits |= 0222; /* w */
        if (c->perms & 4) bits |= 0111; /* x */
        if (c->perms & 8) { /* X: only if dir or any x already set */
            if (is_dir || (result & 0111))
                bits |= 0111;
        }

        /* Restrict to the named classes */
        int class_mask = 0;
        if (classes & 1) class_mask |= 0700;
        if (classes & 2) class_mask |= 0070;
        if (classes & 4) class_mask |= 0007;

        int affected = bits & class_mask;

        switch (c->op) {
        case '+': result |= (mode_t)affected; break;
        case '-': result &= (mode_t)~affected; break;
        case '=': result = (result & (mode_t)~class_mask) | (mode_t)affected; break;
        }
    }
    return result;
}

/* Apply the parsed mode spec to a single path (following symlinks via stat).
   Returns 0 on success, -1 on failure (diagnostic already printed). */
static int apply_to_path(const char *path, const mode_spec_t *spec) {
    struct stat st;
    if (stat(path, &st) != 0) {
        fprintf(stderr, "new_chmod: cannot access '%s': %s\n",
                path, strerror(errno));
        return -1;
    }

    int is_dir = S_ISDIR(st.st_mode);
    mode_t current = st.st_mode & 07777;
    mode_t new_mode;

    if (spec->is_octal) {
        new_mode = spec->octal_value;
    } else {
        mode_t special = current & 07000;
        mode_t perm_bits = current & 00777;
        mode_t new_perm = apply_symbolic(perm_bits, spec->clauses,
                                         spec->n_clauses, is_dir);
        new_mode = special | new_perm;
    }

    if (chmod(path, new_mode) != 0) {
        fprintf(stderr, "new_chmod: cannot change mode of '%s': %s\n",
                path, strerror(errno));
        return -1;
    }
    return 0;
}

/* Byte-wise comparison for qsort of directory entry names. */
static int compare_names(const void *a, const void *b) {
    const char *na = *(const char *const *)a;
    const char *nb = *(const char *const *)b;
    return strcmp(na, nb);
}

/* Recursive pre-order walk: apply mode to dir, then to entries in ascending
   byte order, descending into subdirectories. Symlinks are skipped. */
static int walk_recursive(const char *path, const mode_spec_t *spec) {
    /* Apply to this directory first */
    if (apply_to_path(path, spec) != 0)
        return -1;

    DIR *dir = opendir(path);
    if (!dir) {
        fprintf(stderr, "new_chmod: cannot open directory '%s': %s\n",
                path, strerror(errno));
        return -1;
    }

    /* Collect entry names */
    struct dirent *entry;
    char **names = NULL;
    int count = 0, capacity = 0;
    int alloc_failed = 0;

    while ((entry = readdir(dir)) != NULL) {
        if (strcmp(entry->d_name, ".") == 0 || strcmp(entry->d_name, "..") == 0)
            continue;
        if (count >= capacity) {
            int new_cap = capacity ? capacity * 2 : 16;
            char **tmp = realloc(names, (size_t)new_cap * sizeof(char *));
            if (!tmp) { alloc_failed = 1; break; }
            names = tmp;
            capacity = new_cap;
        }
        names[count] = strdup(entry->d_name);
        if (!names[count]) { alloc_failed = 1; break; }
        count++;
    }
    closedir(dir);

    if (alloc_failed) {
        for (int i = 0; i < count; i++) free(names[i]);
        free(names);
        return -1;
    }

    /* Sort by name (byte order) */
    qsort(names, (size_t)count, sizeof(char *), compare_names);

    int any_failed = 0;
    for (int i = 0; i < count; i++) {
        size_t plen = strlen(path);
        size_t nlen = strlen(names[i]);
        char *full = malloc(plen + 1 + nlen + 1);
        if (full) {
            memcpy(full, path, plen);
            full[plen] = '/';
            memcpy(full + plen + 1, names[i], nlen + 1);

            struct stat est;
            if (lstat(full, &est) == 0) {
                if (S_ISLNK(est.st_mode)) {
                    /* skip symlinks during traversal */
                } else if (S_ISDIR(est.st_mode)) {
                    if (walk_recursive(full, spec) != 0)
                        any_failed = 1;
                } else {
                    if (apply_to_path(full, spec) != 0)
                        any_failed = 1;
                }
            } else {
                fprintf(stderr, "new_chmod: cannot access '%s': %s\n",
                        full, strerror(errno));
                any_failed = 1;
            }
            free(full);
        }
        free(names[i]);
    }
    free(names);

    return any_failed ? -1 : 0;
}

int main(int argc, char *argv[]) {
    int recursive = 0;
    int start = 1;

    /* Parse options (only -R / --recursive and -- are recognized) */
    while (start < argc) {
        if (strcmp(argv[start], "--") == 0) {
            start++;
            break;
        } else if (strcmp(argv[start], "-R") == 0) {
            recursive = 1;
            start++;
        } else if (strcmp(argv[start], "--recursive") == 0) {
            recursive = 1;
            start++;
        } else if (argv[start][0] == '-' && argv[start][1] != '\0') {
            fprintf(stderr, "new_chmod: unknown option '%s'\n", argv[start]);
            exit(1);
        } else {
            break;
        }
    }

    if (start >= argc)
        usage_exit();

    const char *mode_str = argv[start];
    int operand_start = start + 1;

    if (operand_start >= argc)
        usage_exit();

    mode_spec_t spec;
    if (parse_mode(mode_str, &spec) != 0) {
        fprintf(stderr, "new_chmod: invalid mode '%s'\n", mode_str);
        exit(1);
    }

    int any_failed = 0;

    for (int i = operand_start; i < argc; i++) {
        const char *path = argv[i];

        if (recursive) {
            struct stat st;
            if (stat(path, &st) == 0 && S_ISDIR(st.st_mode)) {
                if (walk_recursive(path, &spec) != 0)
                    any_failed = 1;
            } else {
                if (apply_to_path(path, &spec) != 0)
                    any_failed = 1;
            }
        } else {
            if (apply_to_path(path, &spec) != 0)
                any_failed = 1;
        }
    }

    return any_failed ? 1 : 0;
}
