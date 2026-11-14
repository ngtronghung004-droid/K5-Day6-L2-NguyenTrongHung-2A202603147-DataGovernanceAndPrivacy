"""PoC PIPELINE for Track T02 (Raw QC Triage) — Group AA1 (Nguyễn Trọng Hùng).

Lab contract = 5 automated steps, run by `python -m src.main ...`:
    01 load      input + provenance check (manifest.csv)
    02 process   multi-feature anomaly detection (blur, glare, dark, compression)
    03 rank      prioritise for a fixed review budget B (B=20)
    04 review    human-in-the-loop: contact sheet -> reviewer decisions -> overrides + audit log
    05 decide    GO / HOLD / REWORK with reason_code + owner, write outputs
"""
from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd

from .common.contact_sheet import render_contact_sheet
from .common.context import RunContext
from .common.decision import Decision, write_decision
from .common.image_ops import brightness_stats, laplacian_variance, load_rgb, to_gray
from .common.manifest import verify_manifest
from .common.review import apply_overrides, load_review_decisions, make_review_queue, write_review_queue
from .metrics.tracks import get_track


# ---------------------------------------------------------------- 01 load
def load(ctx: RunContext) -> dict:
    """Step 1: Verify data provenance via manifest.csv and load image metadata."""
    manifest_path = ctx.input_dir / "manifest.csv"
    problems = verify_manifest(manifest_path) if manifest_path.exists() else [{"problem": "no_manifest"}]
    if problems:
        ctx.audit.log(actor="pipeline", action="provenance_problems", item_id=str(manifest_path), after=problems[:20])
        if ctx.config.get("strict_provenance", True):
            raise ValueError(f"provenance check failed ({len(problems)} problems), first: {problems[:3]}")

    images_path = ctx.input_dir / "images.csv"
    images_df = pd.read_csv(images_path) if images_path.exists() else None
    return {
        "manifest": pd.read_csv(manifest_path) if manifest_path.exists() else None,
        "images": images_df,
    }


def _compute_jpeg_blockiness(gray: np.ndarray) -> float:
    """Detects 8x8 JPEG grid boundary artifacts."""
    H, W = gray.shape
    if H < 16 or W < 16:
        return 1.0
    # Horizontal grid boundary differences (multiples of 8)
    cols_boundary = np.arange(7, W - 1, 8)
    cols_internal = np.arange(3, W - 1, 8)
    diff_boundary = np.abs(gray[:, cols_boundary] - gray[:, cols_boundary + 1]).mean()
    diff_internal = np.abs(gray[:, cols_internal] - gray[:, cols_internal + 1]).mean()
    return float(diff_boundary / (diff_internal + 1e-4))


# ---------------------------------------------------------------- 02 process
def process(ctx: RunContext, data: dict) -> pd.DataFrame:
    """Step 2: Multi-feature anomaly scoring aware of camera and lighting slices."""
    if ctx.track != "t02":
        raise NotImplementedError(f"Track {ctx.track} not implemented in PoC pipeline; implement for your track")
    spec = get_track(ctx.track)
    images: pd.DataFrame = data["images"].copy()
    
    scores = []
    pred_types = []
    actions = []
    reasons = []

    for _, row in images.iterrows():
        rel_path = row["path"]
        img_path = ctx.input_dir / rel_path
        if not img_path.exists():
            img_path = Path(rel_path)

        img = load_rgb(img_path)
        gray = to_gray(img)
        
        # 1. Sharpness & contrast
        lap_var = laplacian_variance(img)
        b_stats = brightness_stats(img)
        mean_b = b_stats["mean"]
        std_b = b_stats["std"]
        p95 = b_stats["p95"]
        p05 = b_stats["p05"]
        frac_dark = b_stats["frac_dark"]
        frac_sat = b_stats["frac_saturated"]
        
        # 2. Camera & lighting optical normalization
        cam = str(row.get("camera_id", "cam_A"))
        light = str(row.get("light", "day"))
        
        # Camera B optics adjustment factor
        cam_factor = 1.35 if cam == "cam_B" else 1.0
        contrast = max(std_b, 4.0)
        norm_sharpness = (lap_var * cam_factor) / (contrast ** 2 + 1.0)
        
        # Blur defect score
        blur_score = float(np.clip((0.042 - norm_sharpness) / 0.035, 0.0, 1.0))
        # Night images have lower ambient edges; discount blur unless truly washed out
        if light == "night":
            blur_score = float(np.clip((0.025 - norm_sharpness) / 0.022, 0.0, 1.0))

        # Glare defect score: large patches of saturated pixels
        glare_score = float(np.clip((frac_sat - 0.035) / 0.10, 0.0, 1.0))
        if p95 < 235:
            glare_score = 0.0

        # Dark defect score: extreme darkness vs legitimate night scene
        # Legitimate night scenes maintain high p95 (> 75) due to street/car lights
        dark_score = float(np.clip((frac_dark - 0.65) / 0.30, 0.0, 1.0) * np.clip((75.0 - p95) / 45.0, 0.0, 1.0))

        # Compression / JPEG artifact score
        blockiness = _compute_jpeg_blockiness(gray)
        comp_score = float(np.clip((blockiness - 1.25) / 0.55, 0.0, 1.0))

        # Aggregate defect detection
        type_scores = {
            "blur": blur_score,
            "glare": glare_score,
            "dark": dark_score,
            "compression": comp_score,
        }
        
        best_type = max(type_scores, key=type_scores.get)
        max_score = type_scores[best_type]

        # Overall composite score (prioritize review for higher anomaly)
        total_score = float(max_score)
        
        if total_score >= 0.35:
            pred_type = best_type
            action = "RECAPTURE" if total_score >= 0.65 else "REVIEW"
            reason = f"{best_type} (score={total_score:.2f})"
        else:
            pred_type = "none"
            action = "KEEP"
            reason = "clean"

        scores.append(round(total_score, 4))
        pred_types.append(pred_type)
        actions.append(action)
        reasons.append(reason)

    images["score"] = scores
    images["pred_defect_type"] = pred_types
    images["pred_action"] = actions
    images["reason"] = reasons
    images["slice"] = images["camera_id"].astype(str) + " / " + images["light"].astype(str)

    return images


# ---------------------------------------------------------------- 03 rank
def rank(ctx: RunContext, scored: pd.DataFrame) -> pd.DataFrame:
    """Step 3: Rank top-B candidates (B=20) and render offline HTML Contact Sheet."""
    budget = int(ctx.param("budget", 20))
    id_col = "image_id" if "image_id" in scored.columns else scored.columns[0]
    
    evidence = "path" if "path" in scored.columns else None
    queue = make_review_queue(
        scored,
        id_col=id_col,
        score_col="score",
        budget=budget,
        reason_col="reason" if "reason" in scored.columns else None,
        action_col="pred_action" if "pred_action" in scored.columns else None,
        slice_col="slice" if "slice" in scored.columns else None,
        evidence_col=evidence,
    )
    
    write_review_queue(queue, ctx.out("review_queue.csv"))
    
    if evidence:
        render_contact_sheet(
            queue,
            ctx.out("contact_sheet.html"),
            image_root=ctx.input_dir,
            title=f"AA1 (Nguyễn Trọng Hùng) - {ctx.track.upper()} QC Review Queue",
        )
    return queue


# ---------------------------------------------------------------- 04 review
def review(ctx: RunContext, scored: pd.DataFrame, queue: pd.DataFrame) -> pd.DataFrame:
    """Step 4: Incorporate human reviewer decisions and write audit trail."""
    reviewed_path = ctx.output_dir / "review_queue_reviewed.csv"
    if reviewed_path.exists():
        reviewed = load_review_decisions(reviewed_path)
        ctx.stats["n_reviewed"] = len(reviewed)
        
        # Apply overrides to action and defect type
        if "pred_action" in scored.columns and "override_value" in reviewed.columns:
            scored = apply_overrides(scored, reviewed, id_col="image_id", value_col="pred_action", audit=ctx.audit)
            ctx.audit.log(actor="reviewer", action="apply_human_overrides", item_id="review_queue", after=f"{len(reviewed)} reviewed")
    return scored


# ---------------------------------------------------------------- 05 decide
def decide(ctx: RunContext, final: pd.DataFrame) -> Decision:
    """Step 5: Operational release gate: GO / HOLD / REWORK with audit evidence."""
    owner = ctx.config.get("owner", "Nguyễn Trọng Hùng - 2A202603147 (QA Lead)")
    budget = int(ctx.param("budget", 20))
    top_items = final.sort_values("score", ascending=False).head(budget)
    
    # Calculate defect concentration in top-B
    high_defect_count = (top_items["score"] >= 0.6).sum()
    defect_ratio = high_defect_count / float(budget)
    
    # Decision policy
    if defect_ratio > 0.65:
        # Batch exhibits excessive critical corruptions requiring physical recapture
        return Decision(
            status="REWORK",
            reason_code="HIGH_DEFECT_BURDEN",
            reason=f"Severe defects detected in {high_defect_count}/{budget} priority items ({defect_ratio:.1%}). Hardware sensor cleaning & recapture recommended.",
            owner=owner,
            scope=ctx.track,
            evidence=[str(ctx.out("ranked_review.csv")), str(ctx.out("review_queue.csv"))],
        )
    elif defect_ratio >= 0.20:
        # Controlled defect rate: prioritized for triage review and release
        return Decision(
            status="GO",
            reason_code="QC_TRIAGE_SUCCESS",
            reason=f"Prioritized triage isolated {high_defect_count} candidate defects within budget B={budget}. Safe to proceed with reviewed exclusions.",
            owner=owner,
            scope=ctx.track,
            evidence=[str(ctx.out("ranked_review.csv"))],
        )
    else:
        # Anomaly rate surprisingly low, hold to verify pipeline calibration
        return Decision(
            status="HOLD",
            reason_code="SUSPICIOUSLY_LOW_DEFECTS",
            reason=f"Only {high_defect_count} candidate defects detected; potential sensor failure or calibration drift.",
            owner=owner,
            scope=ctx.track,
        )


def run(ctx: RunContext) -> None:
    """Lab Contract Execution Runner."""
    spec = get_track(ctx.track)
    data = load(ctx)
    scored = process(ctx, data)
    ctx.stats["n_items"] = len(scored)
    
    queue = rank(ctx, scored)
    final = review(ctx, scored, queue)
    
    # Sort and export required prediction file
    out_cols = spec.pred_columns + [c for c in final.columns if c not in spec.pred_columns]
    final_sorted = final.sort_values("score", ascending=False)
    final_sorted[out_cols].to_csv(ctx.out(spec.pred_file), index=False)
    
    decision = decide(ctx, final_sorted)
    write_decision(decision, ctx.out("decision.json"), ctx.out("decision_log.csv"))
