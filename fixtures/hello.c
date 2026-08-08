#include <norx/syscall.h>

__attribute__((noreturn, used)) void _start(void)
{
    for (;;) {
        __asm__ volatile ("" ::: "memory");
    }
}
