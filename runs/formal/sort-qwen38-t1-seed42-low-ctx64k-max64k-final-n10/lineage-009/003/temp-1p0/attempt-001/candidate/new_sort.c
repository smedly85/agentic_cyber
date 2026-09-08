#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>

typedef struct {
    unsigned char *data;
    size_t len;
    size_t input_order;
} Line;

static int flag_reverse = 0;
static int flag_fold = 0;
static int flag_unique = 0;

static int char_fold(int c) {
    if (flag_fold) {
        return tolower((unsigned char)c);
    }
    return c;
}

static int compare_lines(const void *a, const void *b) {
    const Line *la = (const Line *)a;
    const Line *lb = (const Line *)b;
    
    size_t min_len = la->len < lb->len ? la->len : lb->len;
    for (size_t i = 0; i < min_len; i++) {
        int ca = char_fold(la->data[i]);
        int cb = char_fold(lb->data[i]);
        if (ca != cb) {
            return ca - cb;
        }
    }
    
    if (la->len < lb->len) return -1;
    if (la->len > lb->len) return 1;
    return 0;
}

static int lines_equal(const Line *a, const Line *b) {
    if (a->len != b->len) return 0;
    for (size_t i = 0; i < a->len; i++) {
        if (char_fold(a->data[i]) != char_fold(b->data[i])) {
            return 0;
        }
    }
    return 1;
}

int main(int argc, char *argv[]) {
    // Parse arguments
    for (int i = 1; i < argc; i++) {
        if (argv[i][0] != '-') {
            fprintf(stderr, "usage: new_sort [-r] [-f] [-u]\n");
            return 2;
        }
        for (char *p = argv[i] + 1; *p; p++) {
            switch (*p) {
                case 'r': flag_reverse = 1; break;
                case 'f': flag_fold = 1; break;
                case 'u': flag_unique = 1; break;
                default:
                    fprintf(stderr, "usage: new_sort [-r] [-f] [-u]\n");
                    return 2;
            }
        }
    }
    
    // Read all lines
    Line *lines = NULL;
    size_t count = 0;
    size_t capacity = 0;
    
    for (;;) {
        int c;
        unsigned char *buffer = NULL;
        size_t len = 0;
        size_t cap = 0;
        
        // Read until newline or EOF
        while ((c = fgetc(stdin)) != EOF && c != '\n') {
            if (len >= cap) {
                cap = cap ? cap * 2 : 64;
                unsigned char *tmp = realloc(buffer, cap);
                if (!tmp) {
                    fprintf(stderr, "memory allocation failed\n");
                    return 1;
                }
                buffer = tmp;
            }
            buffer[len++] = (unsigned char)c;
        }
        
        // If we got no data and hit EOF, we're done
        if (len == 0 && c == EOF) {
            free(buffer);
            break;
        }
        
        // Add line to lines array
        if (count >= capacity) {
            capacity = capacity ? capacity * 2 : 64;
            Line *tmp = realloc(lines, capacity * sizeof(Line));
            if (!tmp) {
                fprintf(stderr, "memory allocation failed\n");
                return 1;
            }
            lines = tmp;
        }
        
        lines[count].data = buffer;
        lines[count].len = len;
        lines[count].input_order = count;
        count++;
    }
    
    // Sort lines
    if (count > 1) {
        qsort(lines, count, sizeof(Line), compare_lines);
    }
    
    // Handle unique if requested
    if (flag_unique && count > 0) {
        size_t out_count = 0;
        for (size_t i = 0; i < count; ) {
            size_t j = i + 1;
            // Find all lines equal to lines[i]
            while (j < count && lines_equal(&lines[i], &lines[j])) {
                j++;
            }
            // Keep the first one (in original input order) among equal lines
            // Since we sorted, we need to find the one with smallest input_order
            size_t best_idx = i;
            for (size_t k = i + 1; k < j; k++) {
                if (lines[k].input_order < lines[best_idx].input_order) {
                    best_idx = k;
                }
            }
            // Write the chosen line
            fwrite(lines[best_idx].data, 1, lines[best_idx].len, stdout);
            fputc('\n', stdout);
            out_count++;
            i = j;
        }
    } else {
        // Output all lines
        for (size_t i = 0; i < count; i++) {
            fwrite(lines[i].data, 1, lines[i].len, stdout);
            fputc('\n', stdout);
        }
    }
    
    // Free memory
    for (size_t i = 0; i < count; i++) {
        free(lines[i].data);
    }
    free(lines);
    
    return 0;
}
