int check(void); int first(void); int second(void);
void transform(void); void write(void);
void run(int n) {
    for (int i = 0; check(); i++) {
        if (check() && first()) {
            while (check()) { transform(); break; }
        } else {
            do { write(); } while (check());
        }
        switch (n) {
            case 0: first();
            case 1: second(); break;
            default: write();
        }
        n = check() ? first() : second();
    }
}
