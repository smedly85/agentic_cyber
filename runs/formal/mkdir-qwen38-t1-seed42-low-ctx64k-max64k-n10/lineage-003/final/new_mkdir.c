#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <errno.h>
#include <unistd.h>

/* --- Mode parsing --- */

static int is_octal_digit(char c) { return c >= '0' && c <= '7'; }

static int parse_octal_mode(const char *s, long *result) {
    long val = 0;
    for (const char *p = s; *p; p++) {
        val = val * 8 + (*p - '0');
        if (val > 07777L) return -1;
    }
    *result = val;
    return 0;
}

static int parse_symbolic_clause(const char *s, size_t len, long *mode) {
    int who_u = 0, who_g = 0, who_o = 0;
    int has_who = 0;
    char op = 0;
    int perm_r = 0, perm_w = 0, perm_x = 0, perm_s = 0, perm_t = 0;
    int has_perm = 0;

    size_t i = 0;

    while (i < len && (s[i] == 'u' || s[i] == 'g' || s[i] == 'o' || s[i] == 'a')) {
        has_who = 1;
        switch (s[i]) {
            case 'u': who_u = 1; break;
            case 'g': who_g = 1; break;
            case 'o': who_o = 1; break;
            case 'a': who_u = who_g = who_o = 1; break;
        }
        i++;
    }

    if (!has_who) who_u = who_g = who_o = 1;

    if (i >= len) return -1;
    op = s[i];
    if (op != '+' && op != '-' && op != '=') return -1;
    i++;

    while (i < len) {
        switch (s[i]) {
            case 'r': perm_r = 1; has_perm = 1; break;
            case 'w': perm_w = 1; has_perm = 1; break;
            case 'x': case 'X': perm_x = 1; has_perm = 1; break;
            case 's': perm_s = 1; has_perm = 1; break;
            case 't': perm_t = 1; has_perm = 1; break;
            default: return -1;
        }
        i++;
    }

    if (op != '=' && !has_perm) return -1;

    long rwx = (perm_r ? 4 : 0) | (perm_w ? 2 : 0) | (perm_x ? 1 : 0);

    if (op == '+') {
        if (who_u) *mode |= rwx << 6;
        if (who_g) *mode |= rwx << 3;
        if (who_o) *mode |= rwx;
        if (perm_s) {
            if (who_u) *mode |= 04000L;
            if (who_g) *mode |= 02000L;
        }
        if (perm_t) *mode |= 01000L;
    } else if (op == '-') {
        if (who_u) *mode &= ~(rwx << 6);
        if (who_g) *mode &= ~(rwx << 3);
        if (who_o) *mode &= ~rwx;
        if (perm_s) {
            if (who_u) *mode &= ~04000L;
            if (who_g) *mode &= ~02000L;
        }
        if (perm_t) *mode &= ~01000L;
    } else { /* '=' */
        if (who_u) *mode = (*mode & ~0700L) | (rwx << 6);
        if (who_g) *mode = (*mode & ~0070L) | (rwx << 3);
        if (who_o) *mode = (*mode & ~0007L) | rwx;
        if (who_u) *mode = (*mode & ~04000L) | (perm_s ? 04000L : 0);
        if (who_g) *mode = (*mode & ~02000L) | (perm_s ? 02000L : 0);
        *mode = (*mode & ~01000L) | (perm_t ? 01000L : 0);
    }

    return 0;
}

static int parse_symbolic_mode(const char *s, long *result) {
    long mode = 0777;
    const char *start = s;
    int any_clause = 0;

    while (1) {
        const char *comma = strchr(start, ',');
        size_t len = comma ? (size_t)(comma - start) : strlen(start);
        if (len == 0) return -1;
        if (parse_symbolic_clause(start, len, &mode) != 0) return -1;
        any_clause = 1;
        if (!comma) break;
        start = comma + 1;
    }

    if (!any_clause) return -1;
    *result = mode;
    return 0;
}

static int parse_mode(const char *s, long *result) {
    if (!s || !s[0]) return -1;

    int all_octal = 1;
    for (const char *p = s; *p; p++) {
        if (!is_octal_digit(*p)) { all_octal = 0; break; }
    }
    if (all_octal) return parse_octal_mode(s, result);

    return parse_symbolic_mode(s, result);
}

/* --- Directory creation --- */

static int create_parents(const char *path, int apply_mode, long final_mode) {
    size_t len = strlen(path);
    if (len == 0) return 0;

    for (size_t i = 0; i <= len; i++) {
        if (path[i] == '/' || path[i] == '\0') {
            size_t prefix_len = i;
            if (prefix_len == 0) continue;

            int is_last = (i == len);

            char *prefix = malloc(prefix_len + 1);
            if (!prefix) { errno = ENOMEM; return -1; }
            memcpy(prefix, path, prefix_len);
            prefix[prefix_len] = '\0';

            struct stat st;
            int rc = stat(prefix, &st);
            if (rc == 0) {
                if (!S_ISDIR(st.st_mode)) {
                    errno = is_last ? EEXIST : ENOTDIR;
                    free(prefix);
                    return -1;
                }
                free(prefix);
            } else if (errno == ENOENT) {
                if (mkdir(prefix, 0777) != 0) {
                    free(prefix);
                    return -1;
                }
                if (is_last && apply_mode) {
                    if (chmod(prefix, (mode_t)final_mode) != 0) {
                        free(prefix);
                        return -1;
                    }
                }
                free(prefix);
            } else {
                free(prefix);
                return -1;
            }
        }
    }
    return 0;
}

int main(int argc, char *argv[]) {
    int i;
    int end_of_options = 0;
    int parents = 0;
    int has_operand = 0;
    int ret = 0;
    int has_mode = 0;
    long mode_value = 0;

    /* First pass: parse options and validate */
    for (i = 1; i < argc; i++) {
        const char *arg = argv[i];
        if (strcmp(arg, "--") == 0) {
            end_of_options = 1;
            continue;
        }
        if (!end_of_options && arg[0] == '-' && arg[1] != '\0') {
            if (strcmp(arg, "-p") == 0 || strcmp(arg, "--parents") == 0) {
                parents = 1;
                continue;
            }
            if (strcmp(arg, "-m") == 0) {
                if (i + 1 >= argc) {
                    fprintf(stderr, "mkdir: option requires an argument -- 'm'\n");
                    return 1;
                }
                i++;
                if (parse_mode(argv[i], &mode_value) != 0) {
                    fprintf(stderr, "mkdir: invalid mode '%s'\n", argv[i]);
                    return 1;
                }
                has_mode = 1;
                continue;
            }
            if (strncmp(arg, "--mode=", 7) == 0) {
                const char *val = arg + 7;
                if (parse_mode(val, &mode_value) != 0) {
                    fprintf(stderr, "mkdir: invalid mode '%s'\n", val);
                    return 1;
                }
                has_mode = 1;
                continue;
            }
            if (strcmp(arg, "--mode") == 0) {
                if (i + 1 >= argc) {
                    fprintf(stderr, "mkdir: option requires an argument -- 'mode'\n");
                    return 1;
                }
                i++;
                if (parse_mode(argv[i], &mode_value) != 0) {
                    fprintf(stderr, "mkdir: invalid mode '%s'\n", argv[i]);
                    return 1;
                }
                has_mode = 1;
                continue;
            }
            fprintf(stderr, "mkdir: unrecognized option '%s'\n", arg);
            fprintf(stderr, "Try 'mkdir --help' for more information.\n");
            return 1;
        }
        has_operand = 1;
    }

    if (!has_operand) {
        fprintf(stderr, "mkdir: missing operand\n");
        fprintf(stderr, "Try 'mkdir --help' for more information.\n");
        return 1;
    }

    /* Second pass: create directories */
    end_of_options = 0;
    for (i = 1; i < argc; i++) {
        const char *arg = argv[i];
        if (strcmp(arg, "--") == 0) {
            end_of_options = 1;
            continue;
        }
        if (!end_of_options && arg[0] == '-' && arg[1] != '\0') {
            if (strcmp(arg, "-m") == 0) { i++; continue; }
            if (strncmp(arg, "--mode=", 7) == 0) continue;
            if (strcmp(arg, "--mode") == 0) { i++; continue; }
            continue;
        }
        if (parents) {
            if (create_parents(arg, has_mode, mode_value) != 0) {
                fprintf(stderr, "mkdir: cannot create directory '%s': %s\n",
                        arg, strerror(errno));
                ret = 1;
            }
        } else {
            if (mkdir(arg, 0777) != 0) {
                fprintf(stderr, "mkdir: cannot create directory '%s': %s\n",
                        arg, strerror(errno));
                ret = 1;
            } else if (has_mode) {
                if (chmod(arg, (mode_t)mode_value) != 0) {
                    fprintf(stderr, "mkdir: cannot set mode for '%s': %s\n",
                            arg, strerror(errno));
                    ret = 1;
                }
            }
        }
    }

    return ret;
}
