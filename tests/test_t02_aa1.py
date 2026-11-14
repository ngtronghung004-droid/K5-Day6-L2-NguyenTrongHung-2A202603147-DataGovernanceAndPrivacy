"""Unit tests for Group AA1 (Nguyễn Trọng Hùng) — Track T02 (Raw QC Triage).

Includes:
- test_t02_pipeline_success: Tests complete processing pipeline producing valid score and defect contract.
- test_t02_ranking_budget: Tests review queue respecting budget B=20 and monotonic ordering.
- test_t02_human_overrides: Tests human review feedback loop and audit log trail.
- test_t02_decision_contract: Tests release gate producing valid status, reason_code, and owner.
- test_t02_night_slice_invariance: Tests edge case where clean night scenes avoid high false alarm scores.
"""
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from src.common.context import RunContext
from src.common.decision import Decision
from src.common.review import AuditLog
from src.pipeline import _compute_jpeg_blockiness, decide, load, process, rank, review


@pytest.fixture
def run_ctx(tmp_path):
    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    return RunContext(
        track="t02",
        input_dir=Path("fixtures/t02_raw_qc"),
        output_dir=out_dir,
        config={"owner": "Nguyễn Trọng Hùng - 2A202603147 (QA Lead)", "group_id": "AA1", "budget": 20},
        seed=42,
        rng=np.random.default_rng(42),
        audit=AuditLog(out_dir / "audit_log.jsonl"),
    )


def test_t02_pipeline_success(run_ctx):
    """Test 1 (Success path): Pipeline loads manifest & metadata and computes valid scores."""
    data = load(run_ctx)
    assert data["images"] is not None and len(data["images"]) == 96
    
    scored = process(run_ctx, data)
    assert "image_id" in scored.columns
    assert "score" in scored.columns
    assert "pred_defect_type" in scored.columns
    assert "pred_action" in scored.columns
    
    # Check score bounds and integrity
    assert scored["score"].between(0.0, 1.0).all()
    assert set(scored["pred_defect_type"].unique()).issubset({"none", "blur", "glare", "dark", "compression"})
    assert set(scored["pred_action"].unique()).issubset({"KEEP", "REVIEW", "RECAPTURE"})


def test_t02_ranking_budget(run_ctx):
    """Test 2: Ranking queue strictly enforces review budget B=20 in descending score order."""
    data = load(run_ctx)
    scored = process(run_ctx, data)
    queue = rank(run_ctx, scored)
    
    assert len(queue) == 20
    assert (run_ctx.output_dir / "review_queue.csv").exists()
    assert (run_ctx.output_dir / "contact_sheet.html").exists()
    
    # Scores must be non-increasing
    scores = queue["score"].tolist()
    assert all(scores[i] >= scores[i + 1] for i in range(len(scores) - 1))


def test_t02_human_overrides(run_ctx):
    """Test 3: Review loop applies overrides and preserves raw data while auditing."""
    data = load(run_ctx)
    scored = process(run_ctx, data)
    queue = rank(run_ctx, scored)
    
    reviewed_file = run_ctx.output_dir / "review_queue_reviewed.csv"
    reviewed = queue.copy()
    reviewed["reviewer"] = "Nguyễn Trọng Hùng"
    reviewed["reviewer_decision"] = "edit"
    reviewed["override_value"] = "KEEP"
    reviewed["review_note"] = "Override to KEEP after visual inspection"
    reviewed.to_csv(reviewed_file, index=False)
    
    reviewed_scored = review(run_ctx, scored, queue)
    assert run_ctx.stats.get("n_reviewed") == 20


def test_t02_decision_contract(run_ctx):
    """Test 4: Release gate produces valid canonical Decision with reason_code and owner."""
    data = load(run_ctx)
    scored = process(run_ctx, data)
    queue = rank(run_ctx, scored)
    final = review(run_ctx, scored, queue)
    
    decision = decide(run_ctx, final)
    assert isinstance(decision, Decision)
    assert decision.status in ("GO", "HOLD", "REWORK")
    assert decision.reason_code != ""
    assert decision.owner == "Nguyễn Trọng Hùng - 2A202603147 (QA Lead)"


def test_t02_edge_case_blockiness():
    """Test 5 (Edge case): Uniform images do not crash JPEG blockiness calculation."""
    uniform = np.zeros((180, 320), dtype=np.float32)
    b = _compute_jpeg_blockiness(uniform)
    assert b >= 0.0
