int first(void); int second(void);
int main(void) { int values[2] = { first(), second() }; return values[0]; }
