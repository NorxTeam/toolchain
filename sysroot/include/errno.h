#ifndef NORX_ERRNO_H
#define NORX_ERRNO_H

#define EBADF 9
#define ECHILD 10
#define EINTR 4
#define EAGAIN 11
#define EFAULT 14
#define EINVAL 22
#define ENOSYS 38
#define EOVERFLOW 75
#define ENOMEM 12

int *__errno_location(void);
#define errno (*__errno_location())

#endif
