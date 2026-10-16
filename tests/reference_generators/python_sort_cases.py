"""Public SORT scenarios, adapted from the C ladder's stdin-only contracts.

No sorting model or predicted GNU outputs live here. All supported invocations
are frozen by GNU 9.11 on Darwin. Interface rejections are explicitly bounded
contract cases because full GNU sort accepts more arguments than this ladder.
"""
import base64
from itertools import combinations


def case(name, data, args=(), flags=(), scope_error=False):
    value = dict(name=name, args=list(args), flags=list(flags), fixture=[],
                 stdin_b64=base64.b64encode(data).decode(), tags=['sorting'], check='golden')
    if scope_error:
        value['scope_error'] = True
    return value


def public_cases():
    cases = []
    for name, data in (
        ('empty', b''), ('one', b'pear'), ('blank', b'\n'),
        ('lexical', b'pear\napple\nbanana\n'),
        ('duplicates', b'b\na\nb\na\n'), ('empty-records', b'\nb\n\na\n'),
        ('prefixes', b'ab\na\naaa\n'), ('spaces', b' b\nb \n\tb\n'),
        ('binary', b'a\x00z\n\xff\na\x00\n\x80\n'),
        ('unterminated', b'z\na'), ('carriage-return', b'b\r\na\r\na\n'),
        ('long', b'z'*65537+b'\n'+b'a'*65538),
    ):
        cases.append(case(name, data))
    cases.append(case('unknown-option', b'b\na\n', ['--invalid-option']))
    for name, args in [('operand', ['input']), ('dash', ['-']),
                       ('terminator', ['--']), ('terminator-operand', ['--', 'input'])]:
        cases.append(case(name, b'b\na\n', args, scope_error=True))
    aliases = {'-r':'--reverse', '-f':'--ignore-case', '-u':'--unique', '-c':'--check'}
    for flag, alias in aliases.items():
        for suffix, args in [('short', [flag]), ('long', [alias]),
                             ('repeat', [flag, flag]), ('cluster', ['-'+flag[1]*2])]:
            cases.append(case(flag[1]+'-'+suffix, b'b\nA\na\nB\na\n', args, [flag]))
        cases.append(case(flag[1]+'-value', b'b\na\n', [alias+'=invalid'], [flag]))
    for n in (2,3,4):
        for flags in combinations(aliases, n):
            label = ''.join(f[1] for f in flags)
            for suffix, args in [('forward', ['-'+label]), ('backward', ['-'+label[::-1]])]:
                cases.append(case('combo-'+label+'-'+suffix,
                                  b'abc\nABC\nAbc\nb\nB\n\x00\n\xff', args, flags))
    for name, data, flags in (
        ('fold-tie', b'a\nA\nb\nB\n', ['-f']),
        ('fold-punctuation', b'Z\n[\nz\n{\n', ['-f']),
        ('first-lower', b'abc\nABC\n', ['-f','-u']),
        ('first-upper', b'ABC\nabc\n', ['-f','-u']),
        ('reverse-first', b'abc\nABC\nb\nB\n', ['-r','-f','-u']),
        ('unique-nul', b'a\x00\na\x00z\na\x00\n', ['-u']),
        ('check-empty', b'', ['-c']), ('check-one', b'x', ['-c']),
        ('check-ordered', b'\na\na\nb\n', ['-c']),
        ('check-late-disorder', b'a\nb\nc\nb\n', ['-c']),
        ('check-reverse', b'z\nb\na', ['-r','-c']),
        ('check-fold-tie', b'a\nA\n', ['-f','-c']),
        ('check-fold-ordered', b'A\na\nB\nb\n', ['-f','-c']),
        ('check-unique-duplicate', b'a\na\n', ['-u','-c']),
        ('check-unique-fold', b'abc\nABC\n', ['-f','-u','-c']),
        ('check-all-ordered', b'z\nb\na\n', ['-r','-f','-u','-c']),
    ):
        cases.append(case(name, data, flags, flags))
    return cases
