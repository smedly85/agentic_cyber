static int parse_clause(const char *s, size_t len, clause_t *out) {
    if (len == 0)
        return -1;

    unsigned char classes = 0;
    unsigned char perms = 0;
    char op = 0;
    int in_class = 1;

    for (size_t i = 0; i < len; i++) {
        char c = s[i];
        if (in_class) {
            if (c == 'u') {
                classes |= 1;
            } else if (c == 'g') {
                classes |= 2;
            } else if (c == 'o') {
                classes |= 4;
            } else if (c == 'a') {
                classes |= 7;
            } else if (c == '+' || c == '-' || c == '=') {
                if (op != 0)
                    return -1;
                op = c;
                in_class = 0;
            } else {
                return -1;
            }
        } else {
            if (c == 'r') {
                perms |= 1;
            } else if (c == 'w') {
                perms |= 2;
            } else if (c == 'x') {
                perms |= 4;
            } else if (c == 'X') {
                perms |= 8;
            } else {
                return -1;
            }
        }
    }

    if (op == 0)
        return -1;

    if (classes == 0)
        classes = 7;

    out->classes = classes;
    out->op = op;
    out->perms = perms;
    return 0;
}
