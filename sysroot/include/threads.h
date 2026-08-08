#ifndef NORX_THREADS_H
#define NORX_THREADS_H

#include <stdint.h>
#include <norx/atomic.h>

typedef uint64_t thrd_t;
typedef int (*thrd_start_t)(void *argument);

enum {
    thrd_success = 0,
    thrd_busy = 1,
    thrd_error = 2,
    thrd_nomem = 3,
    thrd_timedout = 4,
};

typedef struct {
    norx_spinlock_t lock;
} mtx_t;

#define MTX_INIT { NORX_SPINLOCK_INIT }

thrd_t thrd_current(void);
int thrd_equal(thrd_t left, thrd_t right);
int thrd_create(thrd_t *thread, thrd_start_t function, void *argument);
int thrd_join(thrd_t thread, int *result);

static inline int mtx_init(mtx_t *mutex, int type)
{
    (void)type;
    mutex->lock.state = 0;
    return thrd_success;
}

static inline int mtx_lock(mtx_t *mutex)
{
    norx_spin_lock(&mutex->lock);
    return thrd_success;
}

static inline int mtx_trylock(mtx_t *mutex)
{
    if (__atomic_test_and_set(&mutex->lock.state, __ATOMIC_ACQUIRE)) {
        return thrd_busy;
    }
    return thrd_success;
}

static inline int mtx_unlock(mtx_t *mutex)
{
    norx_spin_unlock(&mutex->lock);
    return thrd_success;
}

static inline void mtx_destroy(mtx_t *mutex)
{
    (void)mutex;
}

#endif
