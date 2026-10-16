void write(void); void validate(void);
static void ordinary(void) { validate(); }
static void parser_name(void) { write(); }
int main(void) { ordinary(); parser_name(); return 0; }
