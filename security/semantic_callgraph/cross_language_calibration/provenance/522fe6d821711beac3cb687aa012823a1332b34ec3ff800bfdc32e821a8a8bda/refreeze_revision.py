"""Regenerate only the audit-corrected source freeze, preserving the old identity."""
from validate_corpus import HERE, read, sha, validate, digest
from revise_preregistration import OLD, write

def main():
    assert read(HERE/'fixture_hashes.json')['calibration_fixture_bundle_sha256']==OLD
    provenance=read(HERE/'revision_provenance.json')
    archive=HERE/provenance['archive']
    for name,expected in provenance['archive_files_sha256'].items():
        assert sha(archive/name)==expected,name
    original=read(archive/'fixture_hashes.json')
    original_manifest=read(archive/'fixture_manifest.json')
    assert digest({'manifest':original_manifest,'sources':original['sources'],'metadata_sha256':original['metadata_sha256']})==OLD
    for source,expected in original['sources'].items():
        assert sha(archive/source.split('cross_language_calibration/',1)[1])==expected
    for name,expected in original['metadata_sha256'].items():assert sha(archive/name)==expected
    revised=validate(require_freeze=False)
    assert revised['calibration_fixture_bundle_sha256']!=OLD
    write(HERE/'fixture_hashes.json',revised)
    validate()
    print(revised['calibration_fixture_bundle_sha256'])

if __name__=='__main__':main()
