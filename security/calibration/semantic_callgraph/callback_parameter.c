static void callback(void) {}
static void wrapper(void (*fn)(void)) { fn(); }
int main(void) { wrapper(callback); return 0; }
