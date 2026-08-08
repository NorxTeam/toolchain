#ifndef NORX_UNISTD_H
#define NORX_UNISTD_H

#include <stddef.h>
#include <stdint.h>

typedef long long ssize_t;
typedef int pid_t;

ssize_t read(int fd, void *buffer, size_t length);
ssize_t write(int fd, const void *buffer, size_t length);
int close(int fd);
pid_t getpid(void);
pid_t gettid(void);
int sched_yield(void);

#endif
