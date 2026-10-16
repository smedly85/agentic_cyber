void validate(void); void transform(void); void write(void);
static void work(void) { transform(); write(); }
int main(void) { validate(); work(); return 0; }
