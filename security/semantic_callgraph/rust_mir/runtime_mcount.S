/* Independent machine-code entry tracer, Linux x86_64 SysV.
 * rustc -Zinstrument-mcount inserts calls after the frame-pointer prologue.
 * Preserve flags, caller-saved GPRs and all XMM registers. No MIR input.
 */
.text
.globl mcount
.type mcount,@function
mcount:
    pushfq
    push %rax
    push %rcx
    push %rdx
    push %rsi
    push %rdi
    push %r8
    push %r9
    push %r10
    push %r11
    sub $264,%rsp
    movdqu %xmm0,0(%rsp)
    movdqu %xmm1,16(%rsp)
    movdqu %xmm2,32(%rsp)
    movdqu %xmm3,48(%rsp)
    movdqu %xmm4,64(%rsp)
    movdqu %xmm5,80(%rsp)
    movdqu %xmm6,96(%rsp)
    movdqu %xmm7,112(%rsp)
    movdqu %xmm8,128(%rsp)
    movdqu %xmm9,144(%rsp)
    movdqu %xmm10,160(%rsp)
    movdqu %xmm11,176(%rsp)
    movdqu %xmm12,192(%rsp)
    movdqu %xmm13,208(%rsp)
    movdqu %xmm14,224(%rsp)
    movdqu %xmm15,240(%rsp)
    mov 344(%rsp),%rdi
    mov 8(%rbp),%rsi
    call mir_trace_record
    movdqu 0(%rsp),%xmm0
    movdqu 16(%rsp),%xmm1
    movdqu 32(%rsp),%xmm2
    movdqu 48(%rsp),%xmm3
    movdqu 64(%rsp),%xmm4
    movdqu 80(%rsp),%xmm5
    movdqu 96(%rsp),%xmm6
    movdqu 112(%rsp),%xmm7
    movdqu 128(%rsp),%xmm8
    movdqu 144(%rsp),%xmm9
    movdqu 160(%rsp),%xmm10
    movdqu 176(%rsp),%xmm11
    movdqu 192(%rsp),%xmm12
    movdqu 208(%rsp),%xmm13
    movdqu 224(%rsp),%xmm14
    movdqu 240(%rsp),%xmm15
    add $264,%rsp
    pop %r11
    pop %r10
    pop %r9
    pop %r8
    pop %rdi
    pop %rsi
    pop %rdx
    pop %rcx
    pop %rax
    popfq
    ret
.size mcount,.-mcount
.section .note.GNU-stack,"",@progbits
