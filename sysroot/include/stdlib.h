#ifndef NORX_STDLIB_H
#define NORX_STDLIB_H

#include <stddef.h>

_Noreturn void abort(void);
_Noreturn void _Exit(int status);
_Noreturn void exit(int status);
int atexit(void (*function)(void));
void *malloc(size_t size);
void *calloc(size_t count, size_t size);
void *realloc(void *pointer, size_t size);
void free(void *pointer);

#endif
