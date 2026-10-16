int first(void); int second(void);
int main(void) { int values[2] = { second(), first() }; return values[0]; }
