"""Regression tests for the ingestion batching.

Postgres refuses any statement with more than 32767 bind parameters. Two things
broke here in sequence, and both are pinned below:

1. A fixed row-count chunk works for narrow tables and blows up on wide ones.
2. Counting the caller's dict keys understates the truth, because SQLAlchemy
   also binds client-side defaults the caller never wrote - `id` from UUIDMixin.
   A batch sized on visible columns alone landed at 33750 parameters, just over.
"""

from app.market.service import (
    IMPLICIT_COLUMN_HEADROOM,
    MAX_BIND_PARAMS,
    PG_MAX_BIND_PARAMS,
    _chunks,
)


def _rows(n: int, columns: int) -> list[dict]:
    return [{f"c{i}": i for i in range(columns)} for _ in range(n)]


def test_no_batch_exceeds_the_postgres_limit_even_with_hidden_columns():
    """The bug: the model adds columns the caller cannot see. Charge for them."""
    for visible in (1, 5, 8, 9, 17, 40, 120):
        actual_columns = visible + IMPLICIT_COLUMN_HEADROOM
        for batch in _chunks(_rows(20_000, visible)):
            params = len(batch) * actual_columns
            assert params <= PG_MAX_BIND_PARAMS, (
                f"{len(batch)} rows x {actual_columns} real cols = {params} params"
            )


def test_the_exact_shape_that_broke_the_news_ingest():
    """8 visible columns, 9 real ones. The old chunker emitted 3750-row batches."""
    for batch in _chunks(_rows(12_000, 8)):
        assert len(batch) * 9 <= PG_MAX_BIND_PARAMS


def test_batches_stay_under_the_configured_ceiling():
    for visible in (8, 9, 40):
        for batch in _chunks(_rows(5_000, visible)):
            assert len(batch) * (visible + IMPLICIT_COLUMN_HEADROOM) <= MAX_BIND_PARAMS


def test_every_row_is_emitted_exactly_once_and_in_order():
    rows = [{"a": i, "b": i, "c": i, "d": i, "e": i, "f": i, "g": i, "h": i}
            for i in range(9_137)]
    seen = [r for batch in _chunks(rows) for r in batch]
    assert len(seen) == len(rows)
    assert [r["a"] for r in seen] == list(range(9_137))


def test_empty_input_yields_nothing():
    assert list(_chunks([])) == []


def test_a_pathologically_wide_row_still_yields_batches():
    batches = list(_chunks(_rows(10, columns=1_000)))
    assert sum(len(b) for b in batches) == 10
    assert all(len(b) >= 1 for b in batches)
