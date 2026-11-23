"""Golden-set field accuracy. Invented data only."""

from alas3.golden import evaluate


def test_receipts_paired_by_total_and_scored_per_field():
    golden = {"pages": [
        {"sha16": "a" * 16, "page": 3, "receipts": [
            {"total": 9000.0, "fecha": "2026-01-05"},
            {"total": 17000.0, "fecha": "2026-01-05"},
        ]},
        {"sha16": "a" * 16, "page": 4, "receipts": [{"total": 4100.0, "pto_vta": 6, "nro_cmp": 18730}]},
        {"sha16": "a" * 16, "page": 5, "receipts": [{"total": 100.0, "fecha": "2026-02-01"}]},  # never extracted
    ]}  # fmt: skip
    extracted = {
        ("a" * 16, 3): [{"total": 17000.0, "fecha": "2025-01-05"}, {"total": 9000.0, "fecha": "2026-01-05"}],
        ("a" * 16, 4): [{"total": 4100.004, "pto_vta": 6, "nro_cmp": 18731}],
    }
    s = evaluate(golden, extracted)
    # p3: 2 totals + 1 fecha right, 1 fecha wrong; p4: total + pto_vta right, nro wrong; p5: both wrong
    assert (s.checked, s.correct) == (9, 5)
    assert len(s.misses) == 4 and any("nro_cmp" in m for m in s.misses)


def test_one_extracted_receipt_answers_one_golden_receipt():
    golden = {"pages": [{"sha16": "b" * 16, "page": 1, "receipts": [{"total": 15000.0}, {"total": 15000.0}]}]}
    s = evaluate(golden, {("b" * 16, 1): [{"total": 15000.0}]})
    assert (s.checked, s.correct) == (2, 1)
