void target(void) {}
void external(void);
void (*global_pointer)(void);
void run(void (*target)(void)) {
    target();
    (*target)();
    global_pointer();
    external();
    unknown();
}
