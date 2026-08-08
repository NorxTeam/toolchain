OUTPUT_FORMAT(elf64-x86-64)
OUTPUT_ARCH(i386:x86-64)
ENTRY(_start)

PHDRS
{
    text PT_LOAD FLAGS(5);
    rodata PT_LOAD FLAGS(4);
    data PT_LOAD FLAGS(6);
    tls PT_TLS FLAGS(4);
}

SECTIONS
{
    /* Keep static user images out of the kernel's low identity mapping. */
    . = 0x400000000000;
    .text : ALIGN(0x1000) {
        KEEP(*(.text._start))
        *(.text .text.* .ltext .ltext.*)
    } :text
    .rodata : ALIGN(0x1000) { *(.rodata .rodata.* .lrodata .lrodata.*) } :rodata
    .tdata : ALIGN(0x1000) { *(.tdata .tdata.* .ltdata .ltdata.*) } :tls
    .tbss : ALIGN(0x1000) { *(.tbss .tbss.* .ltbss .ltbss.*) } :tls
    .data : ALIGN(0x1000) { *(.data .data.* .ldata .ldata.*) } :data
    .bss (NOLOAD) : ALIGN(0x1000) {
        *(.bss .bss.* .lbss .lbss.*)
        *(COMMON)
    } :data
    /DISCARD/ : { *(.eh_frame .eh_frame.*) *(.gcc_except_table .gcc_except_table.*) *(.comment) *(.note.GNU-stack) }
}
