import logical_phonology as lp
import pytest
from pydantic import ValidationError

from snc2fst.errors import RuleError
from snc2fst.models import Rule

FS = lp.FeatureSystem(frozenset(["F1", "F2", "F3"]))

VALID_RULE = {
    "Id": "R1",
    "Inr": [["+F1", "-F2"]],
    "Trm": [["+F3"]],
    "Dir": "L",
    "Out": "INR[1]",
}


def test_valid_rule() -> None:
    assert Rule.model_validate(VALID_RULE)


def test_empty_id_raises() -> None:
    rule = {**VALID_RULE, "Id": ""}
    with pytest.raises(ValidationError):
        Rule.model_validate(rule)


@pytest.mark.parametrize("bad_id", ["R/1", "my rule", "R.1", "R@1"])
def test_malformed_id(bad_id: str) -> None:
    rule = {**VALID_RULE, "Id": bad_id}
    with pytest.raises(ValidationError):
        Rule.model_validate(rule)


def test_invalid_dir() -> None:
    rule = {**VALID_RULE, "Dir": "X"}
    with pytest.raises(ValidationError):
        Rule.model_validate(rule)


def test_malformed_inr_missing_feature_name() -> None:
    rule = {**VALID_RULE, "Inr": [["+"]]}
    with pytest.raises(ValidationError):
        Rule.model_validate(rule)


def test_malformed_inr_missing_sign() -> None:
    rule = {**VALID_RULE, "Inr": [["F1"]]}
    with pytest.raises(ValidationError):
        Rule.model_validate(rule)


def test_unknown_feature_raises_rule_error() -> None:
    rule = Rule.model_validate({**VALID_RULE, "Inr": [["+UNKNOWN_FEATURE"]]})
    with pytest.raises(RuleError):
        rule.inr_as_ncs(FS)


def test_starred_feature_expands_to_union() -> None:
    rule = Rule.model_validate(
        {
            "Id": "R1",
            "Inr": [["*F1"]],
            "Trm": [],
            "Dir": "L",
            "Out": "INR[1]",
        }
    )
    ncs = rule.inr_as_ncs(FS)
    # segments with +F1 and -F1 both match
    assert ncs.matches_at(FS.word([FS.segment({"F1": lp.POS})]), 0)
    assert ncs.matches_at(FS.word([FS.segment({"F1": lp.NEG})]), 0)
    # underspecified segment with no F1 value → should not match
    no_f1 = FS.segment({"F2": lp.POS})
    assert not ncs.matches_at(FS.word([no_f1]), 0)


def test_starred_with_valued_features() -> None:
    rule = Rule.model_validate(
        {
            "Id": "R2",
            "Inr": [["*F1", "+F2"]],
            "Trm": [],
            "Dir": "L",
            "Out": "INR[1]",
        }
    )
    ncs = rule.inr_as_ncs(FS)
    # +F1+F2 → matches
    assert ncs.matches_at(
        FS.word([FS.segment({"F1": lp.POS, "F2": lp.POS})]), 0
    )
    # -F1+F2 → matches
    assert ncs.matches_at(
        FS.word([FS.segment({"F1": lp.NEG, "F2": lp.POS})]), 0
    )
    # +F1-F2 → does not match (+F2 required)
    assert not ncs.matches_at(
        FS.word([FS.segment({"F1": lp.POS, "F2": lp.NEG})]), 0
    )
