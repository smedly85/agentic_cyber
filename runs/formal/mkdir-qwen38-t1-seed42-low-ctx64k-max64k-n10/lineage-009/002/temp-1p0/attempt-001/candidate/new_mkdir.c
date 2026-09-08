#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>

/* --- Mode parsing --- */

static int parse_octal_mode(const char *s, mode_t *result)
{
    size_t len = strlen(s);
    if (len == 0)
        return -1;
    unsigned val = 0;
    for (size_t i = 0; i < len; i++) {
        if (s[i] < '0' || s[i] > '7')
            return -1;
        val = val * 8u + (unsigned)(s[i] - '0');
        if (val > 07777u)
            return -1;
    }
    *result = (mode_t)val;
    return 0;
}

static int apply_clause(const char *p, const char *end, mode_t *mode)
{
    int has_u = 0, has_g = 0, has_o = 0;
    int has_class = 0;
    while (p < end) {
        if (*p == 'u') { has_u = 1; has_class = 1; }
        else if (*p == 'g') { has_g = 1; has_class = 1; }
        else if (*p == 'o') { has_o = 1; has_class = 1; }
        else if (*p == 'a') { has_u = has_g = has_o = 1; has_class = 1; }
        else break;
        p++;
    }
    if (!has_class)
        has_u = has_g = has_o = 1;

    if (p >= end)
        return -1;
    char op = *p;
    if (op != '+' && op != '-' && op != '=')
        return -1;
    p++;

    int has_r = 0, has_w = 0, has_x = 0, has_s = 0, has_t = 0;
    while (p < end) {
        if (*p == 'r') has_r = 1;
        else if (*p == 'w') has_w = 1;
        else if (*p == 'x' || *p == 'X') has_x = 1;
        else if (*p == 's') has_s = 1;
        else if (*p == 't') has_t = 1;
        else return -1;
        p++;
    }

    unsigned rwx = 0;
    if (has_r) rwx |= 4u;
    if (has_w) rwx |= 2u;
    if (has_x) rwx |= 1u;

    if (op == '+') {
        if (has_u && rwx) *mode |= ((mode_t)rwx << 6) & 0700;
        if (has_g && rwx) *mode |= ((mode_t)rwx << 3) & 0070;
        if (has_o && rwx) *mode |= (mode_t)(rwx & 7u);
        if (has_s) {
            if (has_u) *mode |= 04000;
            if (has_g) *mode |= 02000;
        }
        if (has_t) *mode |= 01000;
    } else if (op == '-') {
        if (has_u && rwx) *mode &= ~(((mode_t)rwx << 6) & 0700);
        if (has_g && rwx) *mode &= ~(((mode_t)rwx << 3) & 0070);
        if (has_o && rwx) *mode &= ~(mode_t)(rwx & 7u);
        if (has_s) {
            if (has_u) *mode &= ~04000;
            if (has_g) *mode &= ~02000;
        }
        if (has_t) *mode &= ~01000;
    } else {
        if (has_u) {
            *mode &= ~0700;
            *mode |= ((mode_t)rwx << 6) & 0700;
            if (has_s) *mode |= 04000;
            else *mode &= ~04000;
        }
        if (has_g) {
            *mode &= ~0070;
            *mode |= ((mode_t)rwx << 3) & 0070;
            if (has_s) *mode |= 02000;
            else *mode &= ~02000;
        }
        if (has_o) {
            *mode &= ~0007;
            *mode |= (mode_t)(rwx & 7u);
            if (has_t) *mode |= 01000;
            else *mode &= ~01000;
        }
    }
    return 0;
}

static int parse_symbolic_mode(const char *s, mode_t *result)
{
    mode_t mode = 0777;
    const char *start = s;
    while (*start) {
        const char *end = start;
        while (*end && *end != ',')
            end++;
        if (end == start)
            return -1;
        if (apply_clause(start, end, &mode) != 0)
            return -1;
        start = end;
        if (*start == ',')
            start++;
    }
    *result = mode;
    return 0;
}

static int parse_mode(const char *s, mode_t *result)
{
    if (!s || *s == '\0')
        return -1;
    if (parse_octal_mode(s, result) == 0)
        return 0;
    return parse_symbolic_mode(s, result);
}

/* --- Directory creation --- */

static int create_parents(const char *path, mode_t final_mode,
                          int *final_created)
{
    size_t len = strlen(path);
    if (len == 0) {
        errno = ENOENT;
        return -1;
    }

    char *buf = malloc(len + 1);
    if (!buf)
        return -1;

    int rc = 0;
    if (final_created)
        *final_created = 0;

    for (size_t i = 0; i < len; i++) {
        buf[i] = path[i];
        buf[i + 1] = '\0';

        if (path[i] != '/' && i != len - 1)
            continue;

        if (strcmp(buf, "/") == 0)
            continue;

        mode_t m = (i == len - 1) ? final_mode : 0777;
        if (mkdir(buf, m) == 0) {
            if (i == len - 1 && final_created)
                *final_created = 1;
            continue;
        }

        int err = errno;
        if (err == EEXIST) {
            struct stat st;
            if (stat(buf, &st) == 0 && S_ISDIR(st.st_mode))
                continue;
            errno = ENOTDIR;
            rc = -1;
            break;
        }
        rc = -1;
        break;
    }

    free(buf);
    return rc;
}

int main(int argc, char *argv[])
{
    int parents = 0;
    int has_mode = 0;
    mode_t mode = 0777;
    const char *mode_str = NULL;
    int options_done = 0;
    int n_operands = 0;

    const char **operands = malloc((size_t)argc * sizeof(const char *));
    if (!operands) {
        fprintf(stderr, "mkdir: memory allocation failed\n");
        return 1;
    }

    for (int i = 1; i < argc; i++) {
        if (options_done) {
            operands[n_operands++] = argv[i];
            continue;
        }
        if (strcmp(argv[i], "--") == 0) {
            options_done = 1;
            continue;
        }
        if (strcmp(argv[i], "-p") == 0 || strcmp(argv[i], "--parents") == 0) {
            parents = 1;
            continue;
        }
        if (strcmp(argv[i], "-m") == 0) {
            if (i + 1 >= argc) {
                fprintf(stderr,
                        "mkdir: option requires an argument -- 'm'\n");
                free(operands);
                return 1;
            }
            i++;
            mode_str = argv[i];
            has_mode = 1;
            continue;
        }
        if (strncmp(argv[i], "--mode=", 7) == 0) {
            mode_str = argv[i] + 7;
            has_mode = 1;
            continue;
        }
        if (strcmp(argv[i], "--mode") == 0) {
            if (i + 1 >= argc) {
                fprintf(stderr,
                        "mkdir: option requires an argument -- 'mode'\n");
                free(operands);
                return 1;
            }
            i++;
            mode_str = argv[i];
            has_mode = 1;
            continue;
        }
        if (argv[i][0] == '-' && argv[i][1] != '\0') {
            fprintf(stderr, "mkdir: unrecognized option '%s'\n"
                    "Try 'mkdir --help' for more information.\n", argv[i]);
            free(operands);
            return 1;
        }
        operands[n_operands++] = argv[i];
    }

    if (n_operands == 0) {
        fprintf(stderr, "mkdir: missing operand\n"
                "Try 'mkdir --help' for more information.\n");
        free(operands);
        return 1;
    }

    if (has_mode) {
        if (parse_mode(mode_str, &mode) != 0) {
            fprintf(stderr, "mkdir: invalid mode '%s'\n", mode_str);
            free(operands);
            return 1;
        }
    }

    int failed = 0;
    for (int i = 0; i < n_operands; i++) {
        if (parents) {
            int created = 0;
            if (create_parents(operands[i], mode, &created) != 0) {
                int err = errno;
                fprintf(stderr,
                        "mkdir: cannot create directory '%s': %s\n",
                        operands[i], strerror(err));
                failed = 1;
            } else if (has_mode && created) {
                chmod(operands[i], mode);
            }
        } else {
            if (mkdir(operands[i], mode) != 0) {
                int err = errno;
                fprintf(stderr,
                        "mkdir: cannot create directory '%s': %s\n",
                        operands[i], strerror(err));
                failed = 1;
            } else if (has_mode) {
                chmod(operands[i], mode);
            }
        }
    }

    free(operands);
    return failed ? 1 : 0;
}
