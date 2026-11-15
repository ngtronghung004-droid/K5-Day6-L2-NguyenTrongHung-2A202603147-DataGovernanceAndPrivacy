"""T02 QA: human overrides, audit evidence and release-gate boundaries.

These tests use synthetic predictions, never instructor ground truth.
"""
import numpy as np
import pandas as pd
import pytest

from src.common.context import RunContext
from src.common.review import AuditLog
from src.pipeline import decide, rank, review


@pytest.fixture
def qa_context(tmp_path):
    return RunContext(
        track="t02",
        input_dir=tmp_path,
        output_dir=tmp_path / "out",
        config={"owner": "QA test", "params": {"budget": 20}},
        seed=42,
        rng=np.random.default_rng(42),
        audit=AuditLog(tmp_path / "out" / "audit_log.jsonl"),
    )


@pytest.fixture
def predictions():
    return pd.DataFrame({
        "image_id": ["qa_1", "qa_2", "qa_3"],
        "score": [0.9, 0.8, 0.7],
        "pred_action": ["RECAPTURE", "RECAPTURE", "REVIEW"],
        "pred_defect_type": ["blur", "dark", "glare"],
    })


@pytest.mark.parametrize("decision", ["edit", "reject", "approve"])
def test_review_override_preserves_raw_predictions_and_audit(
    qa_context, predictions, decision
):
    raw = predictions.copy(deep=True)
    queue = rank(qa_context, predictions)
    reviewed = queue.iloc[:1].copy()
    reviewed["reviewer"] = "QA reviewer (test fixture)"
    reviewed["reviewer_decision"] = decision
    reviewed["override_value"] = "KEEP"
    reviewed["review_note"] = "Synthetic review used only by this test"
    reviewed.to_csv(qa_context.out("review_queue_reviewed.csv"), index=False)
    qa_context.audit.log(actor="test", action="before_review", item_id="batch")
    audit_before = qa_context.audit.path.read_bytes()

    result = review(qa_context, predictions, queue)

    pd.testing.assert_frame_equal(predictions, raw)
    assert qa_context.stats["n_reviewed"] == 1
    assert qa_context.audit.path.read_bytes().startswith(audit_before)
    pd.testing.assert_frame_equal(result.iloc[1:], raw.iloc[1:])
    pd.testing.assert_series_equal(result["score"], raw["score"])
    pd.testing.assert_series_equal(result["pred_defect_type"], raw["pred_defect_type"])
    overrides = [event for event in qa_context.audit.read()
                 if event["action"].startswith("override:")]
    if decision in {"edit", "reject"}:
        assert result.loc[0, "pred_action"] == "KEEP"
        assert len(overrides) == 1
        event = overrides[0]
        assert event["actor"] == "QA reviewer (test fixture)"
        assert event["action"] == f"override:{decision}"
        assert event["item_id"] == "qa_1"
        assert event["before"] == "RECAPTURE"
        assert event["after"] == "KEEP"
        assert event["reason"] == "Synthetic review used only by this test"
        assert event["ts"]
    else:
        pd.testing.assert_frame_equal(result, raw)
        assert not overrides


@pytest.mark.parametrize(
    "reviewer,decision,error",
    [("", "edit", "no `reviewer`"),
     ("QA reviewer", "invalid_decision", "unknown reviewer_decision")],
)
def test_review_rejects_invalid_feedback(
    qa_context, predictions, reviewer, decision, error
):
    raw = predictions.copy(deep=True)
    queue = rank(qa_context, predictions)
    reviewed = queue.iloc[:1].copy()
    reviewed["reviewer"] = reviewer
    reviewed["reviewer_decision"] = decision
    reviewed["override_value"] = "KEEP"
    reviewed.to_csv(qa_context.out("review_queue_reviewed.csv"), index=False)

    with pytest.raises(ValueError, match=error):
        review(qa_context, predictions, queue)

    pd.testing.assert_frame_equal(predictions, raw)
    assert not qa_context.audit.read()


def test_review_without_feedback_keeps_predictions(qa_context, predictions):
    raw = predictions.copy(deep=True)
    queue = rank(qa_context, predictions)

    result = review(qa_context, predictions, queue)

    pd.testing.assert_frame_equal(result, raw)
    assert qa_context.stats.get("n_reviewed", 0) == 0
    assert not qa_context.audit.read()


@pytest.mark.parametrize(
    "severe_count,status,reason_code",
    [(0, "HOLD", "SUSPICIOUSLY_LOW_DEFECTS"),
     (3, "HOLD", "SUSPICIOUSLY_LOW_DEFECTS"),
     (4, "GO", "QC_TRIAGE_SUCCESS"),
     (13, "GO", "QC_TRIAGE_SUCCESS"),
     (14, "REWORK", "HIGH_DEFECT_BURDEN"),
     (20, "REWORK", "HIGH_DEFECT_BURDEN")],
)
def test_decision_gate_budget20_boundaries(
    qa_context, severe_count, status, reason_code
):
    # 0.60 counts as severe; 0.59 does not. A 21st low-score item stays outside B.
    final = pd.DataFrame({"score": [0.60] * severe_count
                          + [0.59] * (20 - severe_count) + [0.0]})
    original = final.copy(deep=True)

    result = decide(qa_context, final)

    assert result.status == status
    assert result.reason_code == reason_code
    assert result.owner == "QA test"
    assert result.scope == "t02"
    assert result.reason
    pd.testing.assert_frame_equal(final, original)
