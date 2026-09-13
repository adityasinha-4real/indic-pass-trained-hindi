"""Integration test: does the evaluation adapter consume the REAL IndicPass
output, unchanged, rather than a re-derivation of it?

Runs the actual frozen pipeline -- :class:`IndicPassMeter`,
:class:`ReferenceAttack`, :class:`CharacterAttack` -- against the same tiny
fixture dictionary ``tests/test_reference_attack.py`` and
``tests/test_character_attack.py`` already use (not the real 298k-entry
IndicDict, for the same reason those files don't: this test exercises the
real code paths, and a tiny, known dictionary lets it state exact
expectations instead of pinning magic numbers from a build artefact that may
not exist in a fresh checkout).

The one thing this file exists to prove: :mod:`scripts.evaluate_model`'s
predictions are *exactly* what an independent call to ``meter.score()`` and
``attack.rank()`` produce for the same password -- the same property
``api/tests/test_api.py::test_api_result_matches_direct_invocation_exactly``
proves for the web adapter.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import evaluate_model  # noqa: E402
from conftest import build_meter  # noqa: E402
from indicpass.password.benchmark import generate_corpus  # noqa: E402
from indicpass.password.character_attack import (  # noqa: E402
    CharacterAttack,
    CharacterAttackSettings,
    CharacterModel,
    dictionary_stem_corpus,
)
from indicpass.password.oov import Taxonomy  # noqa: E402
from indicpass.password.reference_attack import (  # noqa: E402
    AttackSettings,
    Lexicon,
    ReferenceAttack,
    dictionary_lexicon_entries,
)
from indicpass.password.result import guesses_from_log10  # noqa: E402

TINY_CATEGORIES = ("indic_word", "english", "random")


@pytest.fixture
def corpus():
    return generate_corpus(seed=3, samples_per_category=3, categories=TINY_CATEGORIES)


@pytest.fixture
def m4_attack(indicdict):
    entries = dictionary_lexicon_entries(indicdict)
    lexicon = Lexicon.build(entries, order="frequency", seed=1)
    return ReferenceAttack.build(lexicon, AttackSettings())


@pytest.fixture
def m5_attack(indicdict):
    words = dictionary_stem_corpus(indicdict)
    settings = CharacterAttackSettings(order=2, precision=0.5)
    model = CharacterModel.train(words, order=settings.order, precision=settings.precision)
    return CharacterAttack.build(model, settings), Taxonomy(words)


def test_predictions_match_direct_meter_calls(
    corpus, indicdict, matcher_settings, scoring_settings, scale, baseline
):
    meter = build_meter(indicdict, matcher_settings, scoring_settings, scale, baseline=baseline)
    predictions = evaluate_model.score_predictions(meter, corpus)

    for sample in corpus:
        direct = meter.score(sample.password)
        assert predictions[sample.sample_id]["indicpass"] == direct.log10_guesses
        assert predictions[sample.sample_id]["baseline"] == direct.baseline_log10_guesses
        # No fabricated PCFG column when no PCFG is attached.
        assert "pcfg" not in predictions[sample.sample_id]


def test_m4_rows_match_direct_attack_calls(
    corpus, indicdict, matcher_settings, scoring_settings, scale, m4_attack
):
    meter = build_meter(indicdict, matcher_settings, scoring_settings, scale)
    predictions = evaluate_model.score_predictions(meter, corpus)
    built = evaluate_model.build_m4_rows(m4_attack, corpus, predictions)
    rows = {row.sample_id: row for row in built}

    for sample in corpus:
        direct = m4_attack.rank(sample.password)
        row = rows[sample.sample_id]
        assert row.covered == direct.covered
        assert row.reference_rank == direct.rank
        assert row.log10_reference_rank == direct.log10_rank
        assert row.unseen_stem == (not m4_attack.stem_in_lexicon(sample.password))


def test_m5_rows_match_direct_attack_calls(
    corpus, indicdict, matcher_settings, scoring_settings, scale, m5_attack
):
    attack, taxonomy = m5_attack
    meter = build_meter(indicdict, matcher_settings, scoring_settings, scale)
    predictions = evaluate_model.score_predictions(meter, corpus)
    built = evaluate_model.build_m5_rows(attack, corpus, taxonomy, predictions)
    rows = {row.sample_id: row for row in built}

    for sample in corpus:
        direct = attack.rank(sample.password)
        row = rows[sample.sample_id]
        assert row.reachable == direct.reachable
        assert row.rank == direct.rank
        assert row.log10_rank == direct.log10_rank
        expected_partition = taxonomy.classify(sample.password, sample.category).partition
        assert row.partition == expected_partition


def test_eval_records_carry_the_same_score_the_meter_produced(
    corpus, indicdict, matcher_settings, scoring_settings, scale, m4_attack, m5_attack
):
    m5, taxonomy = m5_attack
    meter = build_meter(indicdict, matcher_settings, scoring_settings, scale)
    predictions = evaluate_model.score_predictions(meter, corpus)
    m4_rows = {r.sample_id: r for r in evaluate_model.build_m4_rows(m4_attack, corpus, predictions)}
    built_m5 = evaluate_model.build_m5_rows(m5, corpus, taxonomy, predictions)
    m5_rows = {r.sample_id: r for r in built_m5}

    columns = evaluate_model.available_columns(list(m4_rows.values()))
    records = evaluate_model.build_records(corpus, m4_rows, m5_rows, columns)
    passwords = {sample.sample_id: sample.password for sample in corpus}

    assert len(records) == len(corpus) * len(columns)
    for record in records:
        direct = meter.score(passwords[record.sample_id])
        if record.model == "indicpass":
            assert record.log10_guesses == direct.log10_guesses
        # to_dict() never contains a password, and its guess_number matches
        # the same conversion result.py itself uses.
        payload = record.to_dict()
        assert "password" not in payload
        assert payload["guess_number"] == guesses_from_log10(record.log10_guesses)


def test_crackable_and_predicted_crackable_semantics():
    record = evaluate_model.EvalRecord(
        sample_id="x-0001", category="indic_word", partition="indic_in_lexicon",
        in_lexicon=True, construction="indic/lower", length=6, model="indicpass",
        log10_guesses=3.0,  # 1000 guesses
        m4_covered=True, m4_log10_rank=2.0,  # observed rank 100
        m5_reachable=False, m5_log10_rank=None,
    )
    assert record.crackable("m4", 1000.0) is True    # 100 <= 1000
    assert record.crackable("m4", 10.0) is False     # 100 > 10
    assert record.crackable("m5", 1e18) is False     # unreachable, never crackable
    assert record.predicted_crackable(10_000.0) is True   # 1000 <= 10_000
    assert record.predicted_crackable(100.0) is False     # 1000 > 100


def test_the_pipeline_is_deterministic(
    corpus, indicdict, matcher_settings, scoring_settings, scale, m4_attack, m5_attack
):
    m5, taxonomy = m5_attack
    meter = build_meter(indicdict, matcher_settings, scoring_settings, scale)

    def run():
        predictions = evaluate_model.score_predictions(meter, corpus)
        m4_built = evaluate_model.build_m4_rows(m4_attack, corpus, predictions)
        m4_rows = {r.sample_id: r for r in m4_built}
        m5_built = evaluate_model.build_m5_rows(m5, corpus, taxonomy, predictions)
        m5_rows = {r.sample_id: r for r in m5_built}
        columns = evaluate_model.available_columns(list(m4_rows.values()))
        records = evaluate_model.build_records(corpus, m4_rows, m5_rows, columns)
        return [r.to_dict() for r in records]

    assert run() == run()
