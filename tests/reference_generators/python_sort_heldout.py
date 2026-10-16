"""Independently maintained SORT dual inputs; never staged for repair.

These are explicit alternate data, not mutations of the public corpus. Shared
case serialization and option-combination enumeration do not share payloads.
"""
from itertools import combinations
from reference_generators.python_sort_cases import case


def heldout_cases():
    cases = []
    def add(dual, data, args=(), flags=(), scope_error=False):
        item = case('heldout-'+dual, data, args, flags, scope_error)
        item['dual_of'] = dual
        cases.append(item)
    for name, data in (
        ('empty', b''), ('one', b'quince\n'), ('blank', b'\n\n\n'),
        ('lexical', b'violet\nplum\nkiwi\nmelon'),
        ('duplicates', b'kiwi\nplum\nkiwi\nplum\nkiwi'),
        ('empty-records', b'plum\n\nkiwi\n\n\n'),
        ('prefixes', b'xyz\nx\nxy\nxyzq'),
        ('spaces', b'\tfruit\n fruit\nfruit \n'),
        ('binary', b'q\x00\xfe\nq\x00\n\xfe\n\x81x'),
        ('unterminated', b'quince\nkiwi\nplum'),
        ('carriage-return', b'q\r\nq\n\rq\n'),
        ('long', b'm'*70001+b'\n'+b'd'*70003+b'\n'),
    ): add(name, data)
    add('unknown-option', b'private invalid input\n', ['--unknown-private-option'])
    for name, args in [('operand', ['private-input']), ('dash', ['-']),
                       ('terminator', ['--']), ('terminator-operand', ['--','private-input'])]:
        add(name, b'private scope input\n', args, scope_error=True)
    aliases = {'-r':'--reverse', '-f':'--ignore-case', '-u':'--unique', '-c':'--check'}
    for flag, alias in aliases.items():
        for suffix, args in [('short', [flag]), ('long', [alias]),
                             ('repeat', [alias, flag, alias]), ('cluster', ['-'+flag[1]*3])]:
            add(flag[1]+'-'+suffix, b'quince\nPLUM\nplum\nQuince\nplum', args, [flag])
        add(flag[1]+'-value', b'private invalid value\n', [alias+'=private-invalid'], [flag])
    for n in (2,3,4):
        for flags in combinations(aliases, n):
            label = ''.join(f[1] for f in flags)
            for suffix, args in [('forward', ['-'+label]), ('backward', ['-'+label[::-1]])]:
                add('combo-'+label+'-'+suffix, b'plum\nPLUM\nPlum\nquince\nQUINCE\n\x01\n\xfe', args, flags)
    for name, data, flags in (
        ('fold-tie', b'q\nQ\np\nP', ['-f']),
        ('fold-punctuation', b'Y\n]private\ny\n}private\n', ['-f']),
        ('first-lower', b'plum\nPLUM\nPlum', ['-f','-u']),
        ('first-upper', b'PLUM\nPlum\nplum', ['-f','-u']),
        ('reverse-first', b'plum\nPLUM\nquince\nQUINCE', ['-r','-f','-u']),
        ('unique-nul', b'p\x00q\np\x00\np\x00q', ['-u']),
        ('check-empty', b'', ['-c']), ('check-one', b'private-single\n', ['-c']),
        ('check-ordered', b'\nkiwi\nplum\nplum\nquince', ['-c']),
        ('check-late-disorder', b'kiwi\nmelon\nplum\nquince\nmelon', ['-c']),
        ('check-reverse', b'quince\nplum\nkiwi\n', ['-r','-c']),
        ('check-fold-tie', b'plum\nPLUM', ['-f','-c']),
        ('check-fold-ordered', b'PLUM\nplum\nQUINCE\nquince', ['-f','-c']),
        ('check-unique-duplicate', b'kiwi\nplum\nplum', ['-u','-c']),
        ('check-unique-fold', b'kiwi\nPLUM\nplum', ['-f','-u','-c']),
        ('check-all-ordered', b'QUINCE\nplum\nKiwi', ['-r','-f','-u','-c']),
    ): add(name, data, flags, flags)
    return cases
