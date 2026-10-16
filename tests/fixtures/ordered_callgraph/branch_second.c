void transform(void); void write(void);
void run(int valid) {
    transform();
    if (valid) {
        write();
    }
}
