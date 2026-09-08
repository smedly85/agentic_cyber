#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <dirent.h>
#include <stdbool.h>
#include <ctype.h>
#include <getopt.h>

#define MAX_CLAUSES 32

typedef struct {
    bool has_u, has_g, has_o;
    int op; /* 0=+, 1=-, 2== */
    bool perm_r, perm_w, perm_x, perm_X;
} clause_t;

typedef struct {
    bool is_octal;
    mode_t octal_value;
    int num_clauses;
    clause_t clauses[MAX_CLAUSES];
} mode_spec_t;

static int parse_mode(const char *mode_str, mode_spec_t *spec)
{
    if (mode_str[0] == '\0')
        return -1;

    bool is_octal = true;
    size_t len = strlen(mode_str);
    if (len > 4)
        is_octal = false;
    for (size_t i = 0; i < len && is_octal; i++) {
        if (mode_str[i] < '0' || mode_str[i] > '7')
            is_octal = false;
    }

    if (is_octal) {
        spec->is_octal = true;
        spec->octal_value = (mode_t)strtol(mode_str, NULL, 8);
        spec->num_clauses = 0;
        return 0;
    }

    spec->is_octal = false;
    spec->num_clauses = 0;
    const char *p = mode_str;

    while (*p) {
        if (spec->num_clauses >= MAX_CLAUSES)
            return -1;

        clause_t *c = &spec->clauses[spec->num_clauses];
        c->has_u = c->has_g = c->has_o = false;
        c->perm_r = c->perm_w = c->perm_x = c->perm_X = false;

        while (*p && *p != '+' && *p != '-' && *p != '=') {
            switch (*p) {
                case 'u': c->has_u = true; break;
                case 'g': c->has_g = true; break;
                case 'o': c->has_o = true; break;
                case 'a': c->has_u = c->has_g = c->has_o = true; break;
                default: return -1;
            }
            p++;
        }
        if (!c->has_u && !c->has_g && !c->has_o)
            c->has_u = c->has_g = c->has_o = true;

        if (*p == '+') { c->op = 0; p++; }
        else if (*p == '-') { c->op = 1; p++; }
        else if (*p == '=') { c->op = 2; p++; }
        else return -1;

        bool any_perm = false;
        while (*p && *p != ',') {
            switch (*p) {
                case 'r': c->perm_r = true; any_perm = true; break;
                case 'w': c->perm_w = true; any_perm = true; break;
                case 'x': c->perm_x = true; any_perm = true; break;
                case 'X': c->perm_X = true; any_perm = true; break;
                default: return -1;
            }
            p++;
        }
        if (!any_perm)
            return -1;

        spec->num_clauses++;

        if (*p == ',') p++;
    }

    if (spec->num_clauses == 0)
        return -1;

    return 0;
}

static mode_t apply_spec(const mode_spec_t *spec, mode_t current, bool is_dir)
{
    if (spec->is_octal)
        return spec->octal_value;

    mode_t result = current;
    for (int i = 0; i < spec->num_clauses; i++) {
        const clause_t *c = &spec->clauses[i];

        mode_t bits = 0;
        if (c->perm_r) bits |= S_IRUSR | S_IRGRP | S_IROTH;
        if (c->perm_w) bits |= S_IWUSR | S_IWGRP | S_IWOTH;
        if (c->perm_x) bits |= S_IXUSR | S_IXGRP | S_IXOTH;
        if (c->perm_X) {
            if (c->op == 0) {
                if (is_dir || (current & (S_IXUSR | S_IXGRP | S_IXOTH)))
                    bits |= S_IXUSR | S_IXGRP | S_IXOTH;
            } else {
                bits |= S_IXUSR | S_IXGRP | S_IXOTH;
            }
        }

        mode_t class_mask = 0;
        if (c->has_u) class_mask |= S_IRUSR | S_IWUSR | S_IXUSR;
        if (c->has_g) class_mask |= S_IRGRP | S_IWGRP | S_IXGRP;
        if (c->has_o) class_mask |= S_IROTH | S_IWOTH | S_IXOTH;

        bits &= class_mask;

        switch (c->op) {
            case 0: result |= bits; break;
            case 1: result &= ~bits; break;
            case 2: result &= ~class_mask; result |= bits; break;
        }
    }
    return result;
}

static int cmp_names(const void *a, const void *b)
{
    return strcmp(*(const char **)a, *(const char **)b);
}

static int walk_dir(const char *path, const mode_spec_t *spec)
{
    int had_error = 0;

    DIR *dir = opendir(path);
    if (!dir) {
        fprintf(stderr, "new_chmod: cannot read directory '%s': %s\n",
                path, strerror(errno));
        return 1;
    }

    char **names = NULL;
    int count = 0, cap = 0;

    for (;;) {
        struct dirent *entry;
        errno = 0;
        entry = readdir(dir);
        if (!entry)
            break;
        if (strcmp(entry->d_name, ".") == 0 || strcmp(entry->d_name, "..") == 0)
            continue;
        if (count == cap) {
            cap = cap ? cap * 2 : 16;
            char **tmp = realloc(names, (size_t)cap * sizeof(char *));
            if (!tmp) {
                for (int j = 0; j < count; j++) free(names[j]);
                free(names);
                closedir(dir);
                return 1;
            }
            names = tmp;
        }
        size_t nlen = strlen(entry->d_name) + 1;
        names[count] = malloc(nlen);
        if (!names[count]) {
            for (int j = 0; j < count; j++) free(names[j]);
            free(names);
            closedir(dir);
            return 1;
        }
        memcpy(names[count], entry->d_name, nlen);
        count++;
    }
    closedir(dir);

    if (count > 1)
        qsort(names, (size_t)count, sizeof(char *), cmp_names);

    for (int i = 0; i < count; i++) {
        size_t plen = strlen(path);
        size_t nlen = strlen(names[i]);
        char *full = malloc(plen + 1 + nlen + 1);
        if (!full) {
            had_error = 1;
            continue;
        }
        memcpy(full, path, plen);
        full[plen] = '/';
        memcpy(full + plen + 1, names[i], nlen + 1);

        struct stat st;
        if (lstat(full, &st) != 0) {
            fprintf(stderr, "new_chmod: cannot access '%s': %s\n",
                    full, strerror(errno));
            had_error = 1;
            free(full);
            continue;
        }

        if (S_ISLNK(st.st_mode)) {
            free(full);
            continue;
        }

        bool is_dir = S_ISDIR(st.st_mode);
        mode_t new_mode = apply_spec(spec, st.st_mode & 07777, is_dir);

        if (chmod(full, new_mode) != 0) {
            fprintf(stderr, "new_chmod: cannot change mode of '%s': %s\n",
                    full, strerror(errno));
            had_error = 1;
        }

        if (is_dir) {
            if (walk_dir(full, spec))
                had_error = 1;
        }

        free(full);
    }

    for (int i = 0; i < count; i++)
        free(names[i]);
    free(names);
    return had_error;
}

int main(int argc, char *argv[])
{
    static const struct option long_options[] = {
        {"recursive", no_argument, NULL, 'R'},
        {NULL, 0, NULL, 0}
    };

    int opt;
    bool recursive = false;

    while ((opt = getopt_long(argc, argv, "+R", long_options, NULL)) != -1) {
        switch (opt) {
            case 'R':
                recursive = true;
                break;
            default:
                fprintf(stderr, "usage: new_chmod [-R] mode file...\n");
                return 1;
        }
    }

    if (optind >= argc) {
        fprintf(stderr, "usage: new_chmod [-R] mode file...\n");
        return 1;
    }

    const char *mode_str = argv[optind++];
    mode_spec_t spec = {0};

    if (parse_mode(mode_str, &spec) != 0) {
        fprintf(stderr, "new_chmod: invalid mode '%s'\n", mode_str);
        return 1;
    }

    if (optind >= argc) {
        fprintf(stderr, "usage: new_chmod [-R] mode file...\n");
        return 1;
    }

    int exit_code = 0;

    for (int i = optind; i < argc; i++) {
        const char *path = argv[i];
        struct stat st;

        if (lstat(path, &st) != 0) {
            fprintf(stderr, "new_chmod: cannot access '%s': %s\n",
                    path, strerror(errno));
            exit_code = 1;
            continue;
        }

        if (recursive && S_ISDIR(st.st_mode)) {
            mode_t new_mode = apply_spec(&spec, st.st_mode & 07777, true);
            if (chmod(path, new_mode) != 0) {
                fprintf(stderr, "new_chmod: cannot change mode of '%s': %s\n",
                        path, strerror(errno));
                exit_code = 1;
            }
            if (walk_dir(path, &spec))
                exit_code = 1;
        } else {
            bool is_dir = S_ISDIR(st.st_mode);
            mode_t new_mode = apply_spec(&spec, st.st_mode & 07777, is_dir);
            if (chmod(path, new_mode) != 0) {
                fprintf(stderr, "new_chmod: cannot change mode of '%s': %s\n",
                        path, strerror(errno));
                exit_code = 1;
            }
        }
    }

    return exit_code;
}
