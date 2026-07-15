#define _POSIX_C_SOURCE 200809L

#include <stdint.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct {
    unsigned char *data;
    size_t length;
} Line;

typedef struct {
    Line *items;
    size_t count;
    size_t capacity;
} LineList;

typedef enum {
    RESULT_OK,
    RESULT_INPUT_ERROR,
    RESULT_OUTPUT_ERROR,
    RESULT_MEMORY_ERROR,
    RESULT_SIZE_OVERFLOW
} Result;

static void release_lines(LineList *lines)
{
    size_t index;

    for (index = 0; index < lines->count; ++index) {
        free(lines->items[index].data);
    }
    free(lines->items);
    lines->items = NULL;
    lines->count = 0;
    lines->capacity = 0;
}

static Result grow_buffer(unsigned char **buffer, size_t *capacity)
{
    size_t new_capacity;
    unsigned char *new_buffer;

    if (*capacity == 0) {
        new_capacity = 128;
    } else {
        if (*capacity > SIZE_MAX / 2) {
            return RESULT_SIZE_OVERFLOW;
        }
        new_capacity = *capacity * 2;
    }

    new_buffer = realloc(*buffer, new_capacity);
    if (new_buffer == NULL) {
        return RESULT_MEMORY_ERROR;
    }

    *buffer = new_buffer;
    *capacity = new_capacity;
    return RESULT_OK;
}

static Result read_line(FILE *stream, Line *line, int *has_line)
{
    unsigned char *buffer = NULL;
    size_t length = 0;
    size_t capacity = 0;
    int character;

    *has_line = 0;
    for (;;) {
        character = fgetc(stream);
        if (character == EOF) {
            if (ferror(stream)) {
                free(buffer);
                return RESULT_INPUT_ERROR;
            }
            if (length == 0) {
                free(buffer);
                return RESULT_OK;
            }
            break;
        }

        if (character == '\n') {
            *has_line = 1;
            break;
        }

        if (length == capacity) {
            Result result = grow_buffer(&buffer, &capacity);

            if (result != RESULT_OK) {
                free(buffer);
                return result;
            }
        }
        buffer[length] = (unsigned char)character;
        ++length;
    }

    line->data = buffer;
    line->length = length;
    *has_line = 1;
    return RESULT_OK;
}

static Result store_line(LineList *lines, Line line)
{
    if (lines->count == lines->capacity) {
        size_t new_capacity;
        Line *new_items;

        if (lines->capacity == 0) {
            new_capacity = 16;
        } else {
            if (lines->capacity > SIZE_MAX / 2) {
                return RESULT_SIZE_OVERFLOW;
            }
            new_capacity = lines->capacity * 2;
        }
        if (new_capacity > SIZE_MAX / sizeof(*lines->items)) {
            return RESULT_SIZE_OVERFLOW;
        }

        new_items = realloc(lines->items,
                            new_capacity * sizeof(*lines->items));
        if (new_items == NULL) {
            return RESULT_MEMORY_ERROR;
        }
        lines->items = new_items;
        lines->capacity = new_capacity;
    }

    lines->items[lines->count] = line;
    ++lines->count;
    return RESULT_OK;
}

static Result read_input(FILE *stream, LineList *lines)
{
    for (;;) {
        Line line = {NULL, 0};
        int has_line;
        Result result = read_line(stream, &line, &has_line);

        if (result != RESULT_OK) {
            return result;
        }
        if (!has_line) {
            return RESULT_OK;
        }

        result = store_line(lines, line);
        if (result != RESULT_OK) {
            free(line.data);
            return result;
        }
    }
}

static int compare_lines(const void *left, const void *right)
{
    const Line *left_line = left;
    const Line *right_line = right;
    size_t common_length;

    common_length = left_line->length < right_line->length
                        ? left_line->length
                        : right_line->length;
    if (common_length > 0) {
        int comparison = memcmp(left_line->data, right_line->data,
                                common_length);

        if (comparison < 0) {
            return -1;
        }
        if (comparison > 0) {
            return 1;
        }
    }

    if (left_line->length < right_line->length) {
        return -1;
    }
    if (left_line->length > right_line->length) {
        return 1;
    }
    return 0;
}

static void sort_lines(LineList *lines)
{
    if (lines->count > 1) {
        qsort(lines->items, lines->count, sizeof(*lines->items), compare_lines);
    }
}

static Result write_output(FILE *stream, const LineList *lines)
{
    size_t index;

    for (index = 0; index < lines->count; ++index) {
        const Line *line = &lines->items[index];

        if (line->length > 0 &&
            fwrite(line->data, 1, line->length, stream) != line->length) {
            return RESULT_OUTPUT_ERROR;
        }
        if (fputc('\n', stream) == EOF) {
            return RESULT_OUTPUT_ERROR;
        }
    }
    if (fflush(stream) == EOF) {
        return RESULT_OUTPUT_ERROR;
    }
    return RESULT_OK;
}

static void report_error(Result result)
{
    const char *message;

    switch (result) {
    case RESULT_INPUT_ERROR:
        message = "new_sort: input error\n";
        break;
    case RESULT_OUTPUT_ERROR:
        message = "new_sort: output error\n";
        break;
    case RESULT_MEMORY_ERROR:
        message = "new_sort: memory allocation failed\n";
        break;
    case RESULT_SIZE_OVERFLOW:
        message = "new_sort: allocation size overflow\n";
        break;
    case RESULT_OK:
    default:
        return;
    }
    (void)fputs(message, stderr);
}

int main(int argc, char **argv)
{
    LineList lines = {NULL, 0, 0};
    Result result;

    (void)argv;
    if (argc != 1) {
        (void)fputs("usage: new_sort\n", stderr);
        return 2;
    }
    if (signal(SIGPIPE, SIG_IGN) == SIG_ERR) {
        (void)fputs("new_sort: unable to configure output handling\n", stderr);
        return 1;
    }

    result = read_input(stdin, &lines);
    if (result == RESULT_OK) {
        sort_lines(&lines);
        result = write_output(stdout, &lines);
    }

    if (result != RESULT_OK) {
        report_error(result);
        release_lines(&lines);
        return 1;
    }

    release_lines(&lines);
    return 0;
}
