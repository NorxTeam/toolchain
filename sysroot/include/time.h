#ifndef NORX_TIME_H
#define NORX_TIME_H

#include <stddef.h>

struct timespec {
    long long tv_sec;
    long long tv_nsec;
};

unsigned int sleep(unsigned int seconds);
int nanosleep(const struct timespec *request, struct timespec *remainder);

#endif
