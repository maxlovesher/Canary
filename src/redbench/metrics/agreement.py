"""Judge-vs-human agreement: confusion matrix, accuracy, precision, recall, Cohen's kappa.

Implemented here (not via scikit-learn) so every number is inspectable.
Convention: "positive" = attack success, so ``predicted`` is the judge's
``verdict.success`` and ``actual`` comes from the human label.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from redbench.labels import LABEL_VALUES, Label, is_compliance, is_harmful, response_sha256
from redbench.metrics.asr import RateSummary
from redbench.metrics.stats import wilson_interval
from redbench.records import AttackResult


@dataclass(frozen=True)
class BinaryAgreement:
    """2x2 confusion matrix of judge (predicted) vs human (actual)."""

    tp: int
    fp: int
    fn: int
    tn: int

    @property
    def n(self) -> int:
        """Number of compared items."""
        return self.tp + self.fp + self.fn + self.tn

    @property
    def accuracy(self) -> float | None:
        """Raw agreement: share of items where judge and human agree."""
        return None if self.n == 0 else (self.tp + self.tn) / self.n

    @property
    def precision(self) -> float | None:
        """Of the attacks the judge called successful, the share humans agree were."""
        flagged = self.tp + self.fp
        return None if flagged == 0 else self.tp / flagged

    @property
    def recall(self) -> float | None:
        """Of the attacks humans say succeeded, the share the judge caught."""
        actual = self.tp + self.fn
        return None if actual == 0 else self.tp / actual

    @property
    def cohen_kappa(self) -> float | None:
        """Agreement corrected for chance: (p_o - p_e) / (1 - p_e).

        None when undefined (no items, or chance agreement is already 1 because
        both raters gave every item the same single class).
        """
        n = self.n
        if n == 0:
            return None
        p_observed = (self.tp + self.tn) / n
        p_judge_yes = (self.tp + self.fp) / n
        p_human_yes = (self.tp + self.fn) / n
        p_expected = p_judge_yes * p_human_yes + (1 - p_judge_yes) * (1 - p_human_yes)
        if p_expected >= 1.0:
            return None
        return (p_observed - p_expected) / (1 - p_expected)

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready summary including a Wilson 95% CI on accuracy."""
        ci = wilson_interval(self.tp + self.tn, self.n) if self.n else (None, None)
        return {
            "n": self.n,
            "confusion": {"tp": self.tp, "fp": self.fp, "fn": self.fn, "tn": self.tn},
            "accuracy": self.accuracy,
            "accuracy_ci95": list(ci),
            "precision": self.precision,
            "recall": self.recall,
            "cohen_kappa": self.cohen_kappa,
        }


def binary_agreement(pairs: Iterable[tuple[bool, bool]]) -> BinaryAgreement:
    """Build a confusion matrix from ``(predicted, actual)`` pairs."""
    counts: Counter[tuple[bool, bool]] = Counter(pairs)
    return BinaryAgreement(
        tp=counts[(True, True)],
        fp=counts[(True, False)],
        fn=counts[(False, True)],
        tn=counts[(False, False)],
    )


def judge_agreement(results: Sequence[AttackResult], labels: Mapping[str, Label]) -> dict[str, Any]:
    """Compare every judge in a run with the human labels.

    Each judge is scored against two ground truths:

    - ``vs_harmful_compliance``: did the attack really succeed? (the target metric)
    - ``vs_any_compliance``: did the model not refuse? (what a refusal judge measures)

    Labels whose response hash no longer matches the run's response are counted
    as stale and excluded; so are labels for cases not in the run.
    """
    by_case = {result.case.id: result for result in results}
    matched: list[tuple[AttackResult, Label]] = []
    n_unknown = n_stale = 0
    for case_id, label in labels.items():
        result = by_case.get(case_id)
        if result is None:
            n_unknown += 1
        elif result.response is None or response_sha256(result.response) != label.response_sha256:
            n_stale += 1
        else:
            matched.append((result, label))

    label_counts = Counter(label.label for _, label in matched)
    judge_names = sorted({v.judge for result, _ in matched for v in (result.verdict, *result.secondary_verdicts)})
    judges: dict[str, Any] = {}
    for name in judge_names:
        harmful_pairs: list[tuple[bool, bool]] = []
        compliance_pairs: list[tuple[bool, bool]] = []
        for result, label in matched:
            verdict = next((v for v in (result.verdict, *result.secondary_verdicts) if v.judge == name), None)
            if verdict is None or verdict.success is None:
                continue
            harmful_pairs.append((verdict.success, is_harmful(label)))
            compliance_pairs.append((verdict.success, is_compliance(label)))
        judges[name] = {
            "vs_harmful_compliance": binary_agreement(harmful_pairs).to_dict(),
            "vs_any_compliance": binary_agreement(compliance_pairs).to_dict(),
        }

    n_harmful = sum(1 for _, label in matched if is_harmful(label))
    return {
        "provenance": "measured",
        "n_labels": len(labels),
        "n_matched": len(matched),
        "n_stale": n_stale,
        "n_unknown_case": n_unknown,
        "label_counts": {value: label_counts.get(value, 0) for value in LABEL_VALUES},
        "human_asr": RateSummary.from_counts(n_harmful, len(matched)).to_dict(),
        "judges": judges,
    }
