struct operations { void (*run)(void); };
static void target(void) {}
static struct operations table = { target };
int main(void) { table.run(); return 0; }
