void transform(void); void write(void);
void run(int valid) {
    if (valid) {
        transform();
    }
    write();
}
