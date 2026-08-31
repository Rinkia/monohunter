"""clean-cache tests — exact-size partial-FITS sweep (pure filesystem, offline)."""

from monohunter.fetch import (
    CORRUPT_FITS_SIZE,
    clean_cache,
    find_corrupt_fits,
)


def _write(path, n_bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\0" * n_bytes)


def test_finds_only_exact_size_fits(tmp_path):
    stub = tmp_path / "mastDownload" / "TESS" / "a" / "part.fits"
    good = tmp_path / "mastDownload" / "TESS" / "b" / "full.fits"
    other = tmp_path / "mastDownload" / "note.txt"      # exact size but not .fits
    _write(stub, CORRUPT_FITS_SIZE)
    _write(good, CORRUPT_FITS_SIZE * 4)
    _write(other, CORRUPT_FITS_SIZE)

    hits = find_corrupt_fits(tmp_path, CORRUPT_FITS_SIZE)

    assert hits == [stub]                                # only the truncated FITS


def test_dry_run_deletes_nothing_then_clean_removes(tmp_path):
    stub = tmp_path / "part.fits"
    good = tmp_path / "full.fits"
    _write(stub, CORRUPT_FITS_SIZE)
    _write(good, CORRUPT_FITS_SIZE * 2)

    n, freed = clean_cache(tmp_path, CORRUPT_FITS_SIZE, dry_run=True)
    assert (n, freed) == (1, CORRUPT_FITS_SIZE)
    assert stub.exists()                                 # dry-run kept it

    n, freed = clean_cache(tmp_path, CORRUPT_FITS_SIZE, dry_run=False)
    assert (n, freed) == (1, CORRUPT_FITS_SIZE)
    assert not stub.exists()                             # gone
    assert good.exists()                                 # untouched


def test_missing_cache_dir_is_empty(tmp_path):
    assert find_corrupt_fits(tmp_path / "nope", CORRUPT_FITS_SIZE) == []
    assert clean_cache(tmp_path / "nope") == (0, 0)
