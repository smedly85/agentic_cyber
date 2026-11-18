#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

static int parse_mode_str(const char *s, mode_t *result, int *digits) {
    if (s == NULL || s[0] == '\0') return 0;
    
    // Check if numeric: all digits 0-7
    int all_numeric = 1;
    for (const char *p = s; *p; p++) {
        if (*p < '0' || *p > '7') {
            all_numeric = 0;
            break;
        }
    }
    
    if (all_numeric) {
        size_t len = strlen(s);
        if (len > 8) return 0;
        *digits = (int)len;
        unsigned long val = strtoul(s, NULL, 8);
        if (val > 07777) return 0;
        *result = (mode_t)val;
        return 1;
    }
    
    // Symbolic mode
    mode_t mode = 0777;
    const char *p = s;
    
    int has_ordinary_perm = 0;
    int has_sticky = 0;
    
    while (*p) {
        // Parse who (one or more of u, g, o, a)
        int who_u = 0, who_g = 0, who_o = 0;
        while (*p == 'u' || *p == 'g' || *p == 'o' || *p == 'a') {
            if (*p == 'u') who_u = 1;
            else if (*p == 'g') who_g = 1;
            else if (*p == 'o') who_o = 1;
            else if (*p == 'a') who_u = who_g = who_o = 1;
            p++;
        }
        
        int who_omitted = (!who_u && !who_g && !who_o);
        
        // Parse operator
        char op;
        if (*p == '+' || *p == '-' || *p == '=') {
            op = *p++;
        } else {
            return 0;
        }
        
        // Parse permissions
        int perm_r = 0, perm_w = 0, perm_x = 0, perm_s = 0, perm_t = 0;
        int copy_from = -1;
        int has_perm = 0;
        
        while (*p && *p != ',') {
            switch (*p) {
                case 'r': perm_r = 1; has_perm = 1; break;
                case 'w': perm_w = 1; has_perm = 1; break;
                case 'x': case 'X': perm_x = 1; has_perm = 1; break;
                case 's': perm_s = 1; has_perm = 1; break;
                case 't': perm_t = 1; has_perm = 1; has_sticky = 1; break;
                case 'u': copy_from = 0; has_perm = 1; break;
                case 'g': copy_from = 1; has_perm = 1; break;
                case 'o': copy_from = 2; has_perm = 1; break;
                default: return 0;
            }
            p++;
        }
        
        if (op != '=' && !has_perm) return 0;
        
        if (perm_r || perm_w || perm_x || copy_from >= 0 || !has_perm)
            has_ordinary_perm = 1;
        
        // Determine affected classes
        int aff_u = who_u || who_omitted;
        int aff_g = who_g || who_omitted;
        int aff_o = who_o || who_omitted;
        
        // Compute ordinary permission bits
        mode_t ord_bits = 0;
        if (copy_from >= 0) {
            mode_t src;
            if (copy_from == 0) src = mode & 0700;
            else if (copy_from == 1) src = mode & 0070;
            else src = mode & 0007;
            
            if (aff_u) ord_bits |= src & 0700;
            if (aff_g) ord_bits |= (src >> 3) & 0070;
            if (aff_o) ord_bits |= (src >> 6) & 0007;
        } else {
            if (perm_r) {
                if (aff_u) ord_bits |= 0400;
                if (aff_g) ord_bits |= 0040;
                if (aff_o) ord_bits |= 0004;
            }
            if (perm_w) {
                if (aff_u) ord_bits |= 0200;
                if (aff_g) ord_bits |= 0020;
                if (aff_o) ord_bits |= 0002;
            }
            if (perm_x) {
                if (aff_u) ord_bits |= 0100;
                if (aff_g) ord_bits |= 0010;
                if (aff_o) ord_bits |= 0001;
            }
        }
        
        // Determine which special bits are affected
        int setuid_affected = perm_s && (who_omitted || who_u || who_o);
        int setgid_affected = perm_s && (who_omitted || who_g || who_o);
        int sticky_affected = perm_t;
        
        // Determine which ordinary bits to clear (for = operator)
        mode_t clear_mask = 0;
        if (op == '=') {
            if (aff_u) clear_mask |= 0700;
            if (aff_g) clear_mask |= 0070;
            if (aff_o) clear_mask |= 0007;
        }
        
        // Apply operation
        if (op == '+') {
            mode |= ord_bits;
            if (setuid_affected) mode |= 04000;
            if (setgid_affected) mode |= 02000;
            if (sticky_affected) mode |= 01000;
        } else if (op == '-') {
            mode &= ~ord_bits;
            if (setuid_affected) mode &= ~04000;
            if (setgid_affected) mode &= ~02000;
            if (sticky_affected) mode &= ~01000;
        } else { /* op == '=' */
            mode &= ~clear_mask;
            mode |= ord_bits;
            
            // Special bits for = operator
            if (setuid_affected) {
                if (perm_s) mode |= 04000;
                else mode &= ~04000;
            }
            if (setgid_affected) {
                if (perm_s) mode |= 02000;
                else mode &= ~02000;
            }
            // Sticky: if o or a is in who, sticky = (perm_t ? set : clear)
            int sticky_addr = (who_omitted || who_o);
            if (sticky_addr) {
                if (perm_t) mode |= 01000;
                else mode &= ~01000;
            }
        }
        
        if (*p == ',') p++;
        else break;
    }
    
    if (!has_ordinary_perm && has_sticky) {
        mode = (mode & ~0777) | 0755;
    }
    *result = mode & 07777;
    return 1;
}

static int ensure_dir(const char *path, int ensure_owner_wx) {
    struct stat lst;
    if (lstat(path, &lst) == 0) {
        if (S_ISDIR(lst.st_mode))
            return 0;
        if (S_ISLNK(lst.st_mode)) {
            struct stat st;
            if (stat(path, &st) == 0 && S_ISDIR(st.st_mode))
                return 0;
            errno = ENOTDIR;
            return -1;
        }
        errno = ENOTDIR;
        return -1;
    }
    if (errno != ENOENT)
        return -1;

    if (mkdir(path, 0777) == -1)
        return -1;

    if (ensure_owner_wx) {
        struct stat st;
        if (stat(path, &st) == 0 && !(st.st_mode & 0300))
            chmod(path, (st.st_mode & 07777) | 0300);
    }
    return 0;
}

static int create_parents(const char *path, mode_t final_mode, int has_final_mode) {
    size_t len = strlen(path);
    if (len == 0) {
        errno = ENOENT;
        return -1;
    }

    char *buf = malloc(len + 1);
    if (!buf) {
        errno = ENOMEM;
        return -1;
    }
    memcpy(buf, path, len + 1);

    int result = 0;
    size_t i = 0;

    while (i < len && buf[i] == '/')
        i++;
    if (i >= len) {
        free(buf);
        return 0;
    }

    while (i < len) {
        size_t comp_start = i;
        while (i < len && buf[i] != '/')
            i++;
        size_t comp_end = i;
        size_t comp_len = comp_end - comp_start;

        if (comp_len == 1 && buf[comp_start] == '.') {
            while (i < len && buf[i] == '/')
                i++;
            continue;
        }

        int is_last = 1;
        {
            size_t j = i;
            while (j < len && buf[j] == '/')
                j++;
            while (j < len) {
                size_t k = j;
                while (k < len && buf[k] != '/')
                    k++;
                size_t next_len = k - j;
                if (!(next_len == 1 && buf[j] == '.')) {
                    is_last = 0;
                    break;
                }
                j = k;
            }
        }

        char saved = buf[comp_end];
        buf[comp_end] = '\0';
        
        if (is_last) {
            // Final component
            if (has_final_mode) {
                if (mkdir(buf, final_mode) == -1) {
                    if (errno == EEXIST) {
                        struct stat st;
                        if (stat(buf, &st) == 0 && S_ISDIR(st.st_mode)) {
                            /* existing directory: idempotent success, do not chmod */
                        } else {
                            errno = ENOTDIR;
                            result = -1;
                        }
                    } else {
                        result = -1;
                    }
                } else {
                    // Ensure mode is correct (umask might have affected it)
                    if (chmod(buf, final_mode) == -1) {
                        result = -1;
                    }
                }
            } else {
                result = ensure_dir(buf, 0);
            }
        } else {
            // Intermediate component
            result = ensure_dir(buf, 1);
        }
        
        buf[comp_end] = saved;
        if (result != 0) {
            break;
        }

        i = comp_end + 1;
    }

    free(buf);
    return result;
}

int main(int argc, char *argv[]) {
    int parents = 0;
    int has_mode = 0;
    mode_t mode_val = 0777;
    int mode_digits = 0;
    char *operands[4096];
    int n_operands = 0;
    int after_ddash = 0;
    
    if (argc < 2) {
        fprintf(stderr, "mkdir: missing operand\n"
                        "Try 'mkdir --help' for more information.\n");
        return 1;
    }
    
    for (int i = 1; i < argc; i++) {
        const char *arg = argv[i];
        
        if (!after_ddash && strcmp(arg, "--") == 0) {
            after_ddash = 1;
            continue;
        }
        
        if (!after_ddash && arg[0] == '-' && arg[1] != '\0') {
            if (strcmp(arg, "-p") == 0 || strcmp(arg, "--parents") == 0) {
                parents = 1;
                continue;
            }
            if (arg[1] == 'm' && arg[2] == '\0') {
                if (i + 1 >= argc) {
                    fprintf(stderr, "mkdir: option requires an argument -- 'm'\n"
                                    "Try 'mkdir --help' for more information.\n");
                    return 1;
                }
                i++;
                if (!parse_mode_str(argv[i], &mode_val, &mode_digits)) {
                    fprintf(stderr, "mkdir: invalid mode '%s'\n", argv[i]);
                    return 1;
                }
                has_mode = 1;
                continue;
            }
            if (arg[1] == 'm' && arg[2] != '\0') {
                if (!parse_mode_str(arg + 2, &mode_val, &mode_digits)) {
                    fprintf(stderr, "mkdir: invalid mode '%s'\n", arg + 2);
                    return 1;
                }
                has_mode = 1;
                continue;
            }
            if (strncmp(arg, "--mode=", 7) == 0) {
                const char *mode_str = arg + 7;
                if (!parse_mode_str(mode_str, &mode_val, &mode_digits)) {
                    fprintf(stderr, "mkdir: invalid mode '%s'\n", mode_str);
                    return 1;
                }
                has_mode = 1;
                continue;
            }
            if (strcmp(arg, "--mode") == 0) {
                if (i + 1 >= argc) {
                    fprintf(stderr, "mkdir: option '--mode' requires an argument\n"
                                    "Try 'mkdir --help' for more information.\n");
                    return 1;
                }
                i++;
                if (!parse_mode_str(argv[i], &mode_val, &mode_digits)) {
                    fprintf(stderr, "mkdir: invalid mode '%s'\n", argv[i]);
                    return 1;
                }
                has_mode = 1;
                continue;
            }
            
            if (arg[1] == '-') {
                fprintf(stderr, "mkdir: unrecognized option '%s'\n"
                                "Try 'mkdir --help' for more information.\n", arg);
            } else {
                fprintf(stderr, "mkdir: invalid option -- '%c'\n"
                                "Try 'mkdir --help' for more information.\n", arg[1]);
            }
            return 1;
        }
        
        if (n_operands >= 4096) {
            fprintf(stderr, "mkdir: too many operands\n");
            return 1;
        }
        operands[n_operands++] = (char *)arg;
    }
    
    if (n_operands == 0) {
        fprintf(stderr, "mkdir: missing operand\n"
                        "Try 'mkdir --help' for more information.\n");
        return 1;
    }
    
    int all_ok = 1;
    for (int i = 0; i < n_operands; i++) {
        const char *path = operands[i];
        errno = 0;
        int rc;
        if (parents) {
            rc = create_parents(path, mode_val, has_mode);
        } else {
            mode_t m = has_mode ? mode_val : 0777;
            rc = mkdir(path, m);
            if (rc == 0 && has_mode) {
                if (chmod(path, mode_val) == -1) {
                    rc = -1;
                }
            }
        }
        if (rc != 0) {
            fprintf(stderr, "mkdir: cannot create directory '%s': %s\n",
                    path, strerror(errno));
            all_ok = 0;
        }
    }
    
    return all_ok ? 0 : 1;
}
