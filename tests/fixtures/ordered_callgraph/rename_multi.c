void write(void); void validate(void);
static void worker(void) { write(); }
static void parse_args(void) { validate(); }
int main(void) { parse_args(); worker(); return 0; }
