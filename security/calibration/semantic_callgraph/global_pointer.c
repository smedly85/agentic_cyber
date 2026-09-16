static void target(void) {}
static void (*global_fp)(void) = target;
int main(void) { global_fp(); return 0; }
