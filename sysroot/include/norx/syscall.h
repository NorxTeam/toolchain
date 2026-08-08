#ifndef NORX_SYSCALL_H
#define NORX_SYSCALL_H

#include <stdint.h>

#define NORX_ABI_VERSION 1u
#define NORX_MAX_ARGS 6u
#define NORX_ERROR_MAX 4095u

typedef uint64_t norx_word_t;
typedef uint64_t norx_pointer_t;

enum norx_syscall_number {
    NORX_SYS_READ = 0,
    NORX_SYS_WRITE = 1,
    NORX_SYS_CLOSE = 3,
    NORX_SYS_WAIT = 61,
    NORX_SYS_EXIT = 60,
    NORX_SYS_GETPID = 39,
    NORX_SYS_GETTID = 186,
    NORX_SYS_YIELD = 24,
    NORX_SYS_SLEEP = 35,
};

enum norx_errno {
    NORX_EBADF = 9,
    NORX_ECHILD = 10,
    NORX_EINTR = 4,
    NORX_EAGAIN = 11,
    NORX_EFAULT = 14,
    NORX_EINVAL = 22,
    NORX_ENOSYS = 38,
    NORX_EOVERFLOW = 75,
};

static inline int norx_is_error(norx_word_t value)
{
    return value >= UINT64_MAX - NORX_ERROR_MAX;
}

static inline int norx_errno_value(norx_word_t value)
{
    return (int)(0u - value);
}

#if defined(__x86_64__)

static inline norx_word_t norx_syscall6(
    norx_word_t number,
    norx_word_t a0,
    norx_word_t a1,
    norx_word_t a2,
    norx_word_t a3,
    norx_word_t a4,
    norx_word_t a5)
{
    norx_word_t result;
    register norx_word_t arg3 __asm__("r10") = a3;
    register norx_word_t arg4 __asm__("r8") = a4;
    register norx_word_t arg5 __asm__("r9") = a5;

    __asm__ volatile (
        "syscall"
        : "=a"(result)
        : "a"(number), "D"(a0), "S"(a1), "d"(a2),
          "r"(arg3), "r"(arg4), "r"(arg5)
        : "rcx", "r11", "memory");
    return result;
}

#elif defined(__aarch64__)

static inline norx_word_t norx_syscall6(
    norx_word_t number,
    norx_word_t a0,
    norx_word_t a1,
    norx_word_t a2,
    norx_word_t a3,
    norx_word_t a4,
    norx_word_t a5)
{
    register norx_word_t x0 __asm__("x0") = a0;
    register norx_word_t x1 __asm__("x1") = a1;
    register norx_word_t x2 __asm__("x2") = a2;
    register norx_word_t x3 __asm__("x3") = a3;
    register norx_word_t x4 __asm__("x4") = a4;
    register norx_word_t x5 __asm__("x5") = a5;
    register norx_word_t x8 __asm__("x8") = number;

    __asm__ volatile (
        "svc #0"
        : "+r"(x0)
        : "r"(x1), "r"(x2), "r"(x3), "r"(x4), "r"(x5), "r"(x8)
        : "memory");
    return x0;
}

#else
#error "Norx syscall ABI supports only x86_64 and aarch64"
#endif

static inline norx_word_t norx_syscall0(norx_word_t number)
{
    return norx_syscall6(number, 0, 0, 0, 0, 0, 0);
}

static inline norx_word_t norx_syscall1(norx_word_t number, norx_word_t a0)
{
    return norx_syscall6(number, a0, 0, 0, 0, 0, 0);
}

static inline norx_word_t norx_syscall2(norx_word_t number, norx_word_t a0, norx_word_t a1)
{
    return norx_syscall6(number, a0, a1, 0, 0, 0, 0);
}

static inline norx_word_t norx_syscall3(
    norx_word_t number, norx_word_t a0, norx_word_t a1, norx_word_t a2)
{
    return norx_syscall6(number, a0, a1, a2, 0, 0, 0);
}

static inline norx_word_t norx_syscall4(
    norx_word_t number, norx_word_t a0, norx_word_t a1, norx_word_t a2, norx_word_t a3)
{
    return norx_syscall6(number, a0, a1, a2, a3, 0, 0);
}

static inline norx_word_t norx_syscall5(
    norx_word_t number,
    norx_word_t a0,
    norx_word_t a1,
    norx_word_t a2,
    norx_word_t a3,
    norx_word_t a4)
{
    return norx_syscall6(number, a0, a1, a2, a3, a4, 0);
}

static inline norx_word_t norx_getpid(void)
{
    return norx_syscall0(NORX_SYS_GETPID);
}

static inline norx_word_t norx_gettid(void)
{
    return norx_syscall0(NORX_SYS_GETTID);
}

static inline norx_word_t norx_wait(norx_word_t child)
{
    return norx_syscall1(NORX_SYS_WAIT, child);
}

static inline norx_word_t norx_yield(void)
{
    return norx_syscall0(NORX_SYS_YIELD);
}

static inline norx_word_t norx_sleep(norx_word_t duration)
{
    return norx_syscall1(NORX_SYS_SLEEP, duration);
}

static inline norx_word_t norx_close(norx_word_t fd)
{
    return norx_syscall1(NORX_SYS_CLOSE, fd);
}

static inline norx_word_t norx_write(
    norx_word_t fd, const void *buffer, norx_word_t length)
{
    return norx_syscall3(NORX_SYS_WRITE, fd, (norx_pointer_t)(uintptr_t)buffer, length);
}

static inline norx_word_t norx_read(
    norx_word_t fd, void *buffer, norx_word_t length)
{
    return norx_syscall3(NORX_SYS_READ, fd, (norx_pointer_t)(uintptr_t)buffer, length);
}

static inline void norx_exit(int status)
{
    (void)norx_syscall1(NORX_SYS_EXIT, (norx_word_t)(int64_t)status);
}

#endif
