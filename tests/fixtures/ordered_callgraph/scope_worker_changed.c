void action(void);
static void worker(void) { action(); action(); }
int main(void) { worker(); return 0; }
