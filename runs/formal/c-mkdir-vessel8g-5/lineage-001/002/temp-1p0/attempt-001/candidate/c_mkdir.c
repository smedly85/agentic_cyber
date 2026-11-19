#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

/* Evaluate a symbolic mode expression starting from 0777 or 0755 for special-bit-only.
   Returns 0 on success, -1 on parse error. */
static int eval_symbolic(const char *expr, mode_t umask, mode_t *result)
{
    // Pre-scan: determine if this is "special-bit-only" (no rwx, no '=')
    int has_rwx = 0;
    int has_equal = 0;
    for (const char *p = expr; *p; p++) {
        if (*p == 'r' || *p == 'w' || *p == 'x' || *p == 'X') has_rwx = 1;
        if (*p == '=') has_equal = 1;
    }
    int special_only = !has_rwx && !has_equal;
    
    mode_t mode = special_only ? 0755 : 0777;
    
    const char *p = expr;
    while (*p) {
        const char *end = strchr(p, ',');
        size_t len = end ? (size_t)(end - p) : strlen(p);
        
        if (len == 0)
            return -1;
        
        size_t pos = 0;
        int has_who = 0;
        int who = 0;
        
        // Parse who (can be multiple chars)
        while (pos < len) {
            char c = p[pos];
            if (c == 'u') { who |= 1; has_who = 1; pos++; }
            else if (c == 'g') { who |= 2; has_who = 1; pos++; }
            else if (c == 'o') { who |= 4; has_who = 1; pos++; }
            else if (c == 'a') { who = 7; has_who = 1; pos++; }
            else break;
        }
        
        if (pos >= len)
            return -1;
        char op = p[pos++];
        if (op != '+' && op != '-' && op != '=')
            return -1;
        
        const char *perms = p + pos;
        size_t plen = len - pos;
        
        int has_r = 0, has_w = 0, has_x = 0, has_s = 0, has_t = 0;
        int copy_src = 0;
        
        for (size_t i = 0; i < plen; i++) {
            char pc = perms[i];
            if (pc == 'r') has_r = 1;
            else if (pc == 'w') has_w = 1;
            else if (pc == 'x' || pc == 'X') has_x = 1;
            else if (pc == 's') has_s = 1;
            else if (pc == 't') has_t = 1;
            else if (pc == 'u') { if (copy_src) return -1; copy_src = 1; }
            else if (pc == 'g') { if (copy_src) return -1; copy_src = 2; }
            else if (pc == 'o') { if (copy_src) return -1; copy_src = 3; }
            else return -1;
        }
        
        if (plen == 0 && op != '=')
            return -1;
        
        mode_t pbits = 0;
        if (copy_src) {
            int shift = (copy_src == 1) ? 6 : (copy_src == 2) ? 3 : 0;
            int val = (int)((mode >> shift) & 7);
            if (has_who) {
                if (who & 1) pbits |= (mode_t)(val << 6) & 0700;
                if (who & 2) pbits |= (mode_t)(val << 3) & 0070;
                if (who & 4) pbits |= (mode_t)val & 0007;
            } else {
                pbits = (mode_t)(val << 6) | (mode_t)(val << 3) | (mode_t)val;
            }
        } else {
            if (has_r) pbits |= 0444;
            if (has_w) pbits |= 0222;
            if (has_x) pbits |= 0111;
            if (has_who) {
                mode_t wm = 0;
                if (who & 1) wm |= 0700;
                if (who & 2) wm |= 0070;
                if (who & 4) wm |= 0007;
                pbits &= wm;
            }
        }
        
        if (op == '+') {
            if (has_who) {
                mode |= pbits;
                if (has_s) {
                    if (who & 1) mode |= 04000;
                    if (who & 2) mode |= 02000;
                }
                if (has_t && (who & 4)) mode |= 01000;
            } else {
                mode |= pbits & ~umask & 0777;
                if (has_s) mode |= 06000;
                if (has_t) mode |= 01000;
            }
        } else if (op == '-') {
            if (has_who) {
                mode &= ~pbits;
                if (has_s) {
                    if (who & 1) mode &= ~04000;
                    if (who & 2) mode &= ~02000;
                }
                if (has_t && (who & 4)) mode &= ~01000;
            } else {
                mode &= ~(pbits & ~umask & 0777);
                if (has_s) mode &= ~06000;
                if (has_t) mode &= ~01000;
            }
        } else {
            if (has_who) {
                mode_t wm = 0;
                if (who & 1) wm |= 0700;
                if (who & 2) wm |= 0070;
                if (who & 4) wm |= 0007;
                
                mode_t new_ord = (mode & ~wm) | (plen ? (pbits & 0777) : 0);
                mode_t special = mode & 07000;
                
                if (has_s && (who & 1)) special |= 04000;
                if (has_s && (who & 2)) special |= 02000;
                
                if (who & 4) {
                    if (has_t) special |= 01000;
                    else special &= ~01000;
                }
                
                // Preserve setuid/setgid if not explicitly addressed
                if (!(who & 1)) special |= mode & 04000;
                if (!(who & 2)) special |= mode & 02000;
                
                mode = (new_ord & 0777) | special;
            } else {
                mode_t filtered = plen ? (pbits & ~umask & 0777) : 0;
                mode = (mode & 07000) | filtered;
            }
        }
        
        if (end)
            p = end + 1;
        else
            break;
    }
    
    *result = mode & 07777;
    return 0;
}

/* Parse a mode string (numeric or symbolic). Returns 0 on success, -1 on error. */
static int parse_mode(const char *str, mode_t umask, mode_t *result)
{
    if (str[0] == '\0')
        return -1;
    
    int is_numeric = 1;
    for (const char *p = str; *p; p++) {
        if (*p < '0' || *p > '7') {
            is_numeric = 0;
            break;
        }
    }
    
    if (is_numeric) {
        char *endp;
        long val = strtol(str, &endp, 8);
        if (*endp != '\0' || val < 0 || val > 07777L)
            return -1;
        *result = (mode_t)val;
        return 0;
    }
    
    return eval_symbolic(str, umask, result);
}

/* Create a directory path with -p semantics.
   Intermediate dirs: 0777 & ~umask, owner w+x ensured.
   Final dir: final_mode if has_mode, else 0777 & ~umask.
   Existing final dir: success without chmod.
   Returns 0 on success, 1 on failure (errno set on failure). */
static int mkdir_p(const char *path, mode_t final_mode, int has_mode)
{
    size_t len = strlen(path);
    char *tmp = malloc(len + 1);
    if (!tmp) {
        errno = ENOMEM;
        return 1;
    }
    memcpy(tmp, path, len + 1);
    
    int rc = 0;
    int is_abs = (path[0] == '/');
    size_t prev_i = 0;
    
    for (size_t i = 0; i <= len && !rc; i++) {
        if (i < len && path[i] != '/')
            continue;
        if (is_abs && i == 0)
            continue;
        
        if (prev_i) tmp[prev_i] = path[prev_i];  // restore previous zero
        tmp[i] = '\0';
        prev_i = i;
        
        const char *prefix = tmp;
        
        if (prefix[0] == '\0')
            continue;
        if (prefix[0] == '/' && prefix[1] == '\0')
            continue;
        
        int is_final = (i == len);
        struct stat st;
        
        if (lstat(prefix, &st) == 0) {
            if (S_ISDIR(st.st_mode))
                continue;
            if (S_ISLNK(st.st_mode) && stat(prefix, &st) == 0 && S_ISDIR(st.st_mode))
                continue;
            errno = ENOTDIR;
            rc = 1;
            break;
        } else if (errno != ENOENT) {
            rc = 1;
            break;
        }
        
        /* Component does not exist; create it. */
        if (mkdir(prefix, 0777) != 0) {
            int e = errno;
            if (e == EEXIST) {
                if (lstat(prefix, &st) == 0) {
                    if (S_ISDIR(st.st_mode))
                        continue;
                    if (S_ISLNK(st.st_mode) && stat(prefix, &st) == 0 && S_ISDIR(st.st_mode))
                        continue;
                }
                errno = ENOTDIR;
            }
            rc = 1;
            break;
        }
        
        if (is_final) {
            if (has_mode) {
                if (chmod(prefix, final_mode) != 0) {
                    rc = 1;
                    break;
                }
            }
        } else {
            /* Ensure owner write+search on intermediate dirs. */
            if (lstat(prefix, &st) == 0 && S_ISDIR(st.st_mode)) {
                mode_t m = st.st_mode & 07777;
                if (!(m & (S_IWUSR | S_IXUSR))) {
                    if (chmod(prefix, m | S_IWUSR | S_IXUSR) != 0) {
                        rc = 1;
                        break;
                    }
                }
            }
        }
    }
    
    free(tmp);
    return rc;
}

int main(int argc, char *argv[])
{
    int has_p = 0;
    char *mode_str = NULL;
    int after_ddash = 0;
    
    // Collect operands during option parsing
    char **operands = malloc(argc * sizeof(char *));
    if (!operands) {
        fprintf(stderr, "mkdir: memory allocation failed\n");
        return 1;
    }
    int operand_count = 0;
    
    /* Phase 1: Parse options and collect operands */
    for (int i = 1; i < argc; i++) {
        if (after_ddash) {
            operands[operand_count++] = argv[i];
            continue;
        }
        char *a = argv[i];
        if (strcmp(a, "--") == 0) {
            after_ddash = 1;
            continue;
        }
        if (a[0] == '-' && a[1] != '\0') {
            if (strcmp(a, "-p") == 0 || strcmp(a, "--parents") == 0) {
                has_p = 1;
                continue;
            }
            if (strcmp(a, "-m") == 0) {
                if (i + 1 < argc) {
                    mode_str = argv[++i];
                } else {
                    fprintf(stderr, "mkdir: option '-m' requires an argument\n");
                    fprintf(stderr, "Try 'mkdir --help' for more information.\n");
                    free(operands);
                    return 1;
                }
                continue;
            }
            if (a[1] == 'm' && a[2] != '\0') {
                mode_str = (char *)&a[2];
                continue;
            }
            if (strcmp(a, "--mode") == 0) {
                if (i + 1 < argc) {
                    mode_str = argv[++i];
                } else {
                    fprintf(stderr, "mkdir: option '--mode' requires an argument\n");
                    fprintf(stderr, "Try 'mkdir --help' for more information.\n");
                    free(operands);
                    return 1;
                }
                continue;
            }
            if (strncmp(a, "--mode=", 7) == 0) {
                mode_str = (char *)&a[7];
                continue;
            }
            if (a[1] == '-') {
                fprintf(stderr, "mkdir: unrecognized option '%s'\n", a);
            } else {
                fprintf(stderr, "mkdir: invalid option -- '%c'\n", a[1]);
            }
            fprintf(stderr, "Try 'mkdir --help' for more information.\n");
            free(operands);
            return 1;
        } else {
            // It's an operand
            operands[operand_count++] = a;
        }
    }
    
    if (operand_count == 0) {
        fprintf(stderr, "mkdir: missing operand\n");
        fprintf(stderr, "Try 'mkdir --help' for more information.\n");
        free(operands);
        return 1;
    }
    
    /* Validate and parse mode if specified. */
    int has_m = (mode_str != NULL);
    mode_t final_mode = 0;
    if (has_m) {
        mode_t um = umask(0);
        (void)umask(um);
        if (parse_mode(mode_str, um, &final_mode) != 0) {
            fprintf(stderr, "mkdir: invalid mode '%s'\n", mode_str);
            free(operands);
            return 1;
        }
    }
    
    /* Phase 2: Create each operand in order; continue after failures. */
    int exit_status = 0;
    for (int i = 0; i < operand_count; i++) {
        const char *path = operands[i];
        
        if (has_p) {
            if (mkdir_p(path, final_mode, has_m) != 0) {
                fprintf(stderr, "mkdir: cannot create directory '%s': %s\n",
                        path, strerror(errno));
                exit_status = 1;
            }
        } else {
            if (mkdir(path, 0777) != 0) {
                int e = errno;
                if (e == EEXIST) {
                    struct stat st;
                    if (lstat(path, &st) == 0 && S_ISDIR(st.st_mode)) {
                        fprintf(stderr, "mkdir: cannot create directory '%s': File exists\n", path);
                    } else if (lstat(path, &st) == 0 && S_ISLNK(st.st_mode) &&
                               stat(path, &st) == 0 && S_ISDIR(st.st_mode)) {
                        fprintf(stderr, "mkdir: cannot create directory '%s': File exists\n", path);
                    } else {
                        fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(e));
                    }
                } else {
                    fprintf(stderr, "mkdir: cannot create directory '%s': %s\n", path, strerror(e));
                }
                exit_status = 1;
            } else {
                if (has_m) {
                    if (chmod(path, final_mode) != 0) {
                        fprintf(stderr, "mkdir: cannot change permissions of '%s': %s\n",
                                path, strerror(errno));
                        exit_status = 1;
                    }
                }
            }
        }
    }
    
    free(operands);
    return exit_status;
}
