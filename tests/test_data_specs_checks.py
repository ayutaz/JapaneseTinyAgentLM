import random

from jtalm.action import validate
from jtalm.data.checks import dedup_key, negation_consistent, well_formed
from jtalm.data.specs import all_specs, sample_requests


def test_every_spec_label_is_valid_and_ids_are_unique() -> None:
    specs = all_specs()
    assert len({s.id for s in specs}) == len(specs)
    for spec in specs:
        assert validate(list(spec.label)) == [], spec.id


def test_spec_categories_and_label_shapes() -> None:
    by_cat: dict[str, list] = {}
    for spec in all_specs():
        by_cat.setdefault(spec.category, []).append(spec)
    assert set(by_cat) == {"single", "multi_action", "negation", "correction", "no_action"}
    assert all(len(s.label) == 1 for s in by_cat["single"])
    assert all(len(s.label) == 2 for s in by_cat["multi_action"])
    assert all(s.label == () for s in by_cat["negation"] + by_cat["no_action"])
    assert all(len(s.label) == 1 for s in by_cat["correction"])


def test_sample_requests_meets_quota() -> None:
    quota = {"single": 20, "negation": 9}
    requests = sample_requests(all_specs(), quota, per_request=8, rng=random.Random(0))
    assert sum(r.category == "single" for r in requests) == 3
    assert sum(r.category == "negation" for r in requests) == 2


def test_well_formed() -> None:
    assert well_formed("右を向いて", "ja")
    assert not well_formed("x", "ja")
    assert not well_formed("look right", "ja")
    assert not well_formed('{"a": 1}', "ja")
    assert well_formed("Look to the right.", "en")


def test_negation_consistency() -> None:
    assert negation_consistent("右を向いて", "single", "ja")
    assert not negation_consistent("右を向かないで", "single", "ja")
    assert negation_consistent("右を向かないで", "negation", "ja")
    assert not negation_consistent("右を向いて", "negation", "ja")
    assert negation_consistent("右じゃなくて左を向いて", "correction", "ja")
    assert negation_consistent("Don't look left.", "negation", "en")


def test_dedup_key_ignores_punctuation_width_and_spaces() -> None:
    assert dedup_key("右を向いて！") == dedup_key("右を 向いて")
    assert dedup_key("ＡＢＣ") == dedup_key("abc")
