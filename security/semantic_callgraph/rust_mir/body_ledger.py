"""Fail-closed body dispositions, kept separately from may-call inference."""
DISPOSITIONS = {'body_available', 'legitimate_external_boundary',
                'intrinsic_with_contract', 'unsupported_required_body', 'missing_required_body'}


def ledger(functions, active):
    rows = []
    for identity in sorted(active):
        row = functions.get(identity, {})
        disposition = row.get('disposition')
        if disposition is None:
            availability = row.get('body_availability')
            disposition = ('body_available' if availability in ('available body', 'generic instantiated body')
                           else 'legitimate_external_boundary' if availability == 'external body'
                           else 'missing_required_body')
        if disposition not in DISPOSITIONS:
            raise ValueError('Unknown required-body disposition: ' + disposition)
        crate = row.get('defining_crate')
        origin = ('local_crate' if row.get('local_definition') else
                  'rebuilt_' + crate if crate in ('core', 'alloc', 'std') else 'dependency')
        rows.append({'instance': identity, 'disposition': disposition,
                     'crate': crate, 'def_path': row.get('def_path'),
                     'origin': origin if disposition == 'body_available' else None,
                     'generic': row.get('generic'), 'source_span': row.get('source'),
                     'compiler_generated': row.get('compiler_generated'),
                     'instance_kind': row.get('instance_kind'),
                     'intrinsic_contract': row.get('intrinsic_contract')})
    return rows
