"""Identifying-value policy for the new Linux namespace only.

The fixed GNU ENOSPC diagnostic contains no input-specific information. Like
exit status 1 and empty stdout, it is shared by independent cases. Keep exact
functional assertions; exclude only this exact constant from identity scanning.
"""
import base64

ENOSPC = b"sort: fflush failed: 'standard output': No space left on device\nsort: write error\n"


def identifying_values(selector, case, values):
    if selector in ('c-sort','rust-sort','py-sort') and case.get('faults', {}).get('stdout') == '/dev/full':
        shared = {ENOSPC.decode(), base64.b64encode(ENOSPC).decode()}
        return [value for value in values if value not in shared]
    return values
