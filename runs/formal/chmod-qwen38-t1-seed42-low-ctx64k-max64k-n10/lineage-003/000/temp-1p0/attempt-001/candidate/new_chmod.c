#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdbool.h>
#include <errno.h>
#include <sys/stat.h>
#include <unistd.h>

// Type to hold parsed symbolic mode operations
typedef struct {
    char *ops;  // Array of operation strings
    int count;
} symbolic_mode_t;

// Free resources used by symbolic_mode_t
static void free_symbolic_mode(symbolic_mode_t *sm) {
    if (sm->ops) {
        for (int i = 0; i < sm->count; i++) {
            free(sm->ops + i * 256); // Assuming max 256 chars per op
        }
        free(sm->ops);
    }
    sm->ops = NULL;
    sm->count = 0;
}

// Check if a string is a valid octal number
static bool is_octal_string(const char *str) {
    if (!str || *str == '\0') return false;
    
    // Check if all characters are octal digits (0-7)
    for (int i = 0; str[i] != '\0'; i++) {
        if (str[i] < '0' || str[i] > '7') {
            return false;
        }
    }
    return true;
}

// Parse an octal string to an integer
static bool parse_octal(const char *str, int *value) {
    if (!str || *str == '\0') return false;
    
    // Check for invalid characters
    for (int i = 0; str[i] != '\0'; i++) {
        if (str[i] < '0' || str[i] > '7') {
            return false;
        }
    }
    
    long val = strtol(str, NULL, 8);
    if (val < 0 || val > 07777) {
        return false;
    }
    
    *value = (int)val;
    return true;
}

// Parse a symbolic mode string
static bool parse_symbolic(const char *str, symbolic_mode_t *sm) {
    if (!str || *str == '\0') return false;
    
    // Count the number of operations (separated by commas)
    int count = 1;
    for (int i = 0; str[i] != '\0'; i++) {
        if (str[i] == ',') count++;
    }
    
    // Allocate space for operations
    sm->ops = malloc(count * 256);
    if (!sm->ops) return false;
    
    sm->count = 0;
    
    // Parse each operation
    const char *start = str;
    const char *end = strchr(str, ',');
    
    while (end) {
        int len = end - start;
        if (len > 0 && len < 256) {
            strncpy(sm->ops + sm->count * 256, start, len);
            sm->ops[sm->count * 256 + len] = '\0';
            sm->count++;
        }
        start = end + 1;
        end = strchr(start, ',');
    }
    
    // Handle the last operation
    if (*start != '\0') {
        int len = strlen(start);
        if (len > 0 && len < 256) {
            strcpy(sm->ops + sm->count * 256, start);
            sm->count++;
        }
    }
    
    // Validate each operation
    for (int i = 0; i < sm->count; i++) {
        const char *op = sm->ops + i * 256;
        const char *p = op;
        
        // Must start with users (u, g, a, o) or be empty (for +, -, =)
        if (*p == '+' || *p == '-' || *p == '=') {
            p++;
        }
        
        // Parse users
        bool has_users = false;
        while (*p == 'u' || *p == 'g' || *p == 'o' || *p == 'a') {
            has_users = true;
            p++;
        }
        
        if (!has_users && op[0] != '+' && op[0] != '-' && op[0] != '=') {
            free_symbolic_mode(sm);
            return false;
        }
        
        // Must have operator
        if (*p != '+' && *p != '-' && *p != '=') {
            free_symbolic_mode(sm);
            return false;
        }
        
        p++;
        
        // Parse permissions
        while (*p) {
            if (*p != 'r' && *p != 'w' && *p != 'x' && *p != 'X' && *p != 's' && *p != 't') {
                free_symbolic_mode(sm);
                return false;
            }
            p++;
        }
    }
    
    return true;
}

// Apply symbolic mode to a mode_t
static mode_t apply_symbolic(symbolic_mode_t *sm, mode_t old_mode, bool is_dir) {
    mode_t new_mode = old_mode;
    
    for (int i = 0; i < sm->count; i++) {
        const char *op = sm->ops + i * 256;
        const char *p = op;
        
        // Determine which users to affect
        bool affect_u = false, affect_g = false, affect_o = false;
        
        // Skip to users part
        while (*p == 'u' || *p == 'g' || *p == 'o' || *p == 'a') {
            if (*p == 'u') affect_u = true;
            if (*p == 'g') affect_g = true;
            if (*p == 'o') affect_o = true;
            if (*p == 'a') affect_u = affect_g = affect_o = true;
            p++;
        }
        
        // If no users specified, default to all
        if (!affect_u && !affect_g && !affect_o) {
            affect_u = affect_g = affect_o = true;
        }
        
        // Get operator
        char op_char = *p;
        p++;
        
        // Parse permissions
        mode_t perms = 0;
        while (*p) {
            switch (*p) {
                case 'r': perms |= 0444; break;
                case 'w': perms |= 0222; break;
                case 'x': perms |= 0111; break;
                case 'X': 
                    if (is_dir || (old_mode & 0111)) {
                        perms |= 0111;
                    }
                    break;
                case 's': 
                    if (affect_u) perms |= 04000; // setuid
                    if (affect_g) perms |= 02000; // setgid
                    break;
                case 't': 
                    if (affect_o) perms |= 01000; // sticky bit
                    break;
            }
            p++;
        }
        
        // Apply operation
        mode_t affected = 0;
        if (affect_u) affected |= 0777; // user bits
        if (affect_g) affected |= 0770; // group bits
        if (affect_o) affected |= 077;  // other bits
        
        // Mask to only the bits we're affecting
        perms &= affected;
        
        switch (op_char) {
            case '+':
                new_mode |= perms;
                break;
            case '-':
                new_mode &= ~perms;
                break;
            case '=':
                // Clear affected bits and set new ones
                new_mode &= ~affected;
                new_mode |= perms;
                break;
        }
    }
    
    return new_mode;
}

/* ---------- main ---------- */

static void die_usage(void)
{
    fprintf(stderr, "usage: new_chmod MODE FILE...\n");
    exit(1);
}

int main(int argc, char *argv[])
{
    if (argc < 2)
        die_usage();

    const char *mode_str = NULL;
    char **operands = NULL;
    int noperands = 0;

    if (strcmp(argv[1], "--") == 0) {
        if (argc < 4)
            die_usage();
        mode_str = argv[2];
        operands = &argv[3];
        noperands = argc - 3;
    } else if (argv[1][0] == '-') {
        fprintf(stderr, "new_chmod: unknown option: %s\n", argv[1]);
        die_usage();
    } else {
        if (argc < 3)
            die_usage();
        mode_str = argv[1];
        operands = &argv[2];
        noperands = argc - 2;
    }

    if (noperands < 1)
        die_usage();

    /* Parse the mode */
    bool octal = false;
    int octal_val = 0;
    symbolic_mode_t sm;

    if (is_octal_string(mode_str)) {
        if (!parse_octal(mode_str, &octal_val)) {
            fprintf(stderr, "new_chmod: invalid mode: %s\n", mode_str);
            return 1;
        }
        octal = true;
    } else {
        if (!parse_symbolic(mode_str, &sm)) {
            fprintf(stderr, "new_chmod: invalid mode: %s\n", mode_str);
            return 1;
        }
    }

    /* Apply to each operand */
    int any_failed = 0;

    for (int i = 0; i < noperands; i++) {
        const char *path = operands[i];
        struct stat st;

        if (stat(path, &st) != 0) {
            fprintf(stderr, "new_chmod: cannot access '%s': %s\n",
                    path, strerror(errno));
            any_failed = 1;
            continue;
        }

        mode_t new_mode;
        if (octal) {
            new_mode = (mode_t)octal_val;
        } else {
            new_mode = apply_symbolic(&sm, st.st_mode, S_ISDIR(st.st_mode));
        }

        if (chmod(path, new_mode) != 0) {
            fprintf(stderr, "new_chmod: cannot change mode of '%s': %s\n",
                    path, strerror(errno));
            any_failed = 1;
        }
    }

    // Clean up
    if (!octal) {
        free_symbolic_mode(&sm);
    }

    return any_failed ? 1 : 0;
}
