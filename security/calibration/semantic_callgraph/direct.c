static void b(void) {}
static void a(void) { b(); }
int main(void) { a(); return 0; }
