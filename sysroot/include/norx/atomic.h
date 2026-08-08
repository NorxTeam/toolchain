#ifndef NORX_ATOMIC_H
#define NORX_ATOMIC_H

#include <stdbool.h>
#include <stdint.h>

typedef struct {
    volatile uint8_t state;
} norx_spinlock_t;

#define NORX_SPINLOCK_INIT { 0 }

static inline void norx_atomic_store_u64(volatile uint64_t *object, uint64_t value)
{
    __atomic_store_n(object, value, __ATOMIC_RELEASE);
}

static inline uint64_t norx_atomic_load_u64(const volatile uint64_t *object)
{
    return __atomic_load_n(object, __ATOMIC_ACQUIRE);
}

static inline uint64_t norx_atomic_fetch_add_u64(volatile uint64_t *object, uint64_t value)
{
    return __atomic_fetch_add(object, value, __ATOMIC_SEQ_CST);
}

static inline bool norx_atomic_compare_exchange_u64(
    volatile uint64_t *object, uint64_t *expected, uint64_t desired)
{
    return __atomic_compare_exchange_n(
        object, expected, desired, false, __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE);
}

static inline void norx_spin_lock(norx_spinlock_t *lock)
{
    while (__atomic_test_and_set(&lock->state, __ATOMIC_ACQUIRE)) {
        __asm__ volatile ("" ::: "memory");
    }
}

static inline void norx_spin_unlock(norx_spinlock_t *lock)
{
    __atomic_clear(&lock->state, __ATOMIC_RELEASE);
}

#endif
