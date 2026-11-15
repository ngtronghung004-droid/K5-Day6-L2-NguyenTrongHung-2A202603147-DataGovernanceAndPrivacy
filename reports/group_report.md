# Group Report — Day 06 Data Lab (Field-to-Release PoC)

> Điền đầy đủ, cụ thể, không viết chung chung. Mọi con số lấy từ file do script sinh ra
> (`reports/metrics_*.json`, `reports/table1_baseline_vs_poc.md`).

## 00 · Header

| Mục | Giá trị |
|---|---|
| Group ID | AA1 |
| Challenge | T02 · Raw QC Triage: ảnh mờ, lóa và thiếu sáng |
| Thành viên (5 thành viên) + vai trò | 1. Nguyễn Trọng Hùng - 2A202603147 (Lead / Integrator) · 2. Nguyễn Tấn Dũng - 2A202603031  (Data & Fixtures)  · 3. Bùi Kim Trại - 2A202603176 (Core Algorithm) · 4. Ngô Thị Minh Quang - 2A202603146 (QA & Unit Tests) · 5. Nguyễn Thị Hương Giang - 2A202603233 (Human Review & Report) |
| Git URL | https://github.com/ngtronghung004-droid/K5-Day6-L2-NguyenTrongHung-2A202603147-DataGovernanceAndPrivacy |
| Tag `demo-180m` (commit) | demo-180m |
| Tag `final-24h` (commit) | final-24h |
| Deadline (giờ VN) | 2026-11-14 |

## 01 · Problem statement

- **Ai bị ảnh hưởng / ai chịu hậu quả khi hệ thống sai?**
  1. *Mô hình Perception xe tự hành (Autonomous Driving):* Nếu nạp ảnh bị mờ nặng, lóa đèn (glare), quá tối hoặc vỡ hình do nén (compression) vào tập train/eval, mô hình sẽ bị ảo giác (hallucination), bỏ lọt vật cản hoặc nhận dạng sai làn đường, trực tiếp đe dọa an toàn giao thông.
  2. *Đội ngũ Human Annotator:* Bị quá tải và lãng phí ngân sách gán nhãn nếu phải lọc thủ công hàng triệu frame thô.
- **Điểm nghẽn cụ thể:**
  Dữ liệu thô thu nhận từ camera xe có tỷ lệ lỗi tự nhiên và nhân tạo (weather, glare, sensor noise). Ngân sách review của chuyên gia chỉ có $B = 20$ ảnh trên mỗi mẻ. Cần thuật toán lọc và xếp hạng (triage) chính xác nhất để 20 ảnh được đưa lên review chứa tối đa các ảnh lỗi thật sự (Defect Recall@B cao nhất).
- **Đầu vào → đầu ra:**
  - *Đầu vào:* 96 ảnh synthetic ($320 \times 180$) và bảng metadata `images.csv` (các trường `image_id, path, camera_id, light, split`).
  - *Đầu ra:* `out/ranked_review.csv` (`image_id, score, pred_defect_type, pred_action`), `review_queue.csv`, `contact_sheet.html`, `audit_log.jsonl` và quyết định `decision.json`.
- **Tiêu chí GO / HOLD / REWORK:**
  - **GO:** Defect Recall@B $\ge 0.80$ và tỉ lệ lỗi sau review trong tầm kiểm soát an toàn.
  - **HOLD:** Điểm số bất thường quá thấp hoặc thiếu mẫu kiểm định theo điều kiện ánh sáng (`night`), cần calibrate lại sensor.
  - **REWORK:** Tỷ lệ khuyết tật nghiêm trọng trong top $B$ vượt quá $65\%$, yêu cầu lau rửa ống kính phần cứng hoặc thu thập lại dữ liệu (recapture).
- **Giả định của nhóm:**
  Các khuyết tật vật lý (quang học mờ, bão hòa ánh sáng, cảm biến phơi sáng sai) biểu hiện qua các đặc trưng thống kê ảnh số (Laplacian, độ bão hòa, phân vị sáng, blockiness) và có thể chuẩn hóa theo từng cấu hình phần cứng camera.

## 02 · Data & provenance

| Split | N | Nguồn / link | License | Synthetic? |
|---|---|---|---|---|
| dev | 56 | fixtures/t02_raw_qc/images.csv | CC0 | Synthetic (320x180) |
| eval / heldout | 40 | fixtures/t02_raw_qc/images.csv (cảnh gốc độc lập) | CC0 | Synthetic (320x180) |

- **Schema & class mapping:** `image_id, path, camera_id (cam_A, cam_B), light (day, dusk, night), split (dev, eval)`.
- **Seed:** 42 · Chia split theo cảnh gốc (`scene_id`) để tránh rò rỉ dữ liệu giữa dev và eval.
- **`manifest.csv` verified (sha256):** Có — Lệnh: `python -m tools.verify_manifests`.
- **Dữ liệu thật dùng (nếu có):** BDD100K validation pack (tùy chọn mở rộng).

## 03 · Research & design

- **References kỹ thuật:**
  1. *Pech-Pacheco et al., "Diatom autofocusing in brightfield microscopy"*: Sử dụng phương sai toán tử Laplace (Laplacian variance) làm proxy đo độ sắc nét (sharpness).
  2. *Wang et al., "Blind Measurement of Blocking Artifacts in Images"*: Đo chênh lệch gradient tại biên khối $8 \times 8$ để phát hiện nén JPEG chất lượng thấp.
  3. *ISO/IEC TR 5259-6:2026 / CVAT automated QA*: Chuẩn hóa đánh giá chất lượng dữ liệu AI theo lát cắt (slice-based data quality).
- **Sơ đồ data flow:**
  `load(manifest & images.csv)` $\rightarrow$ `process(multi-feature scoring & slice normalization)` $\rightarrow$ `rank(top-B queue & contact sheet)` $\rightarrow$ `review(overrides & audit log)` $\rightarrow$ `decide(GO/HOLD/REWORK)` $\rightarrow$ `out/ranked_review.csv`.
- **Trade-offs đã cân nhắc:**
  - Không dùng mô hình Deep Learning nặng để đảm bảo chạy CPU cực nhanh ($< 50$ ms/item) và hoàn toàn offline 100%.
  - Chuẩn hóa độ sắc nét theo độ tương phản cục bộ $\text{LapVar} / (\sigma^2 + 1)$ thay vì ngưỡng tĩnh, giúp tránh phạt nhầm ảnh ban đêm.

## 04 · Baseline vs PoC

- **Baseline:** Ngưỡng Laplacian variance tĩnh toàn ảnh (`src.examples.random_baseline` hoặc single Laplacian threshold).
- **PoC:** Bộ lọc kết hợp đa đặc trưng (sharpness/contrast, glare saturation, extreme dark, JPEG blockiness) chuẩn hoá theo slice.
- **Cùng budget / cùng heldout / cùng seed:** Xác nhận cùng seed 42, cùng budget B=20, cùng tập dữ liệu fixtures/t02_raw_qc.

**Bảng 1 · Baseline vs PoC & hard slices** (sinh tự động từ `reports/table1_baseline_vs_poc.md`):

| Metric (unit) | Slice | Baseline | PoC | Δ abs | Δ rel | Better | N |
|---|---|---|---|---|---|---|---|
| **Defect Recall@B** (GT defects in top-B / GT defects) | all | 0.4500 | 0.9000 | +0.4500 | +100.0% | higher | 56 |
| Precision@B (GT defects in top-B / B) | all | 0.4500 | 0.9000 | +0.4500 | +100.0% | higher | 56 |
| False alarm in top-B (clean images in top-B / clean images) | light=day | 0.1500 | 0.0500 | -0.1000 | -66.7% | lower | 24 |
| False alarm in top-B (clean images in top-B / clean images) | light=dusk | 0.2500 | 0.0625 | -0.1875 | -75.0% | lower | 16 |
| False alarm in top-B (clean images in top-B / clean images) | light=night | 0.6250 | 0.0625 | -0.5625 | -90.0% | lower | 16 |
| Runtime / 100 items (s) | all | 0.0905 | 0.5084 | +0.4179 | n/a | lower | 96 |

## 05 · Evaluation protocol

- **Primary metric:** Defect Recall@B ($B=20$ trên split `eval`).
  $$\text{Defect Recall@B} = \frac{\text{Số ảnh lỗi thật sự trong Top } B}{\text{Tổng số ảnh lỗi thật sự trong split eval}}$$
- **Secondary metrics:** Precision@B, False Alarm rate trong Top $B$ theo slice ánh sáng (`light=day/dusk/night`).
- **Lệnh evaluate chuẩn:**
  ```bash
  python -m src.evaluate --track t02 --pred out/poc/ranked_review.csv --out reports/metrics_poc.json
  ```

## 06 · Result slices & Failure cases

- **Slice Performance:**
  - Slice ban ngày (`day`): Defect Recall@B đạt 95%, False Alarm giảm từ 15% xuống 5%.
  - Slice hoàng hôn (`dusk`): False Alarm giảm từ 25% xuống 6.25%.
  - Slice ban đêm (`night`): Bước đột phá lớn nhất, False Alarm giảm mạnh từ 62.5% xuống 6.25% nhờ loại trừ ảnh đêm có đèn xe hợp lệ.
- **Failure case 1 (Glare cục bộ ban ngày):** Ảnh `img_05_1` có biển số phản xạ ánh nắng chói gắt nhưng cảnh vật xung quanh sắc nét. Baseline dùng Laplacian toàn ảnh không phát hiện được. PoC phát hiện nhờ đặc trưng phân vị sáng $p_{95} > 240$ và tỷ lệ pixel bão hòa $> 245$.
- **Failure case 2 (Ảnh đêm tự nhiên):** Ảnh `img_01_0` là ảnh đêm bình thường của camera A. Do đêm tự nhiên có ít cạnh biên, baseline Laplacian phạt nhầm khiến false alarm ban đêm lên đến 62.5%. PoC chuẩn hóa theo độ tương phản cục bộ và giảm false alarm xuống còn 6.25%.
- **Latency / compute:** Máy CPU Intel x86_64, Windows 11, thời gian xử lý: 0.488s / 96 ảnh (trung bình ~5.1 ms/ảnh).

## 07 · Human & decision

- **Review queue:** File `out/poc/review_queue.csv` gồm đúng $B=20$ ảnh có `score` nghi lỗi cao nhất.
- **Contact sheet HTML:** File `out/poc/contact_sheet.html` cho phép xem trực quan ảnh, lý do nghi vấn, nhập quyết định `approve/reject/edit` và export CSV.
- **Audit log:** Mọi thao tác override lưu vết append-only tại `out/poc/audit_log.jsonl` có actor, action, timestamp. Đã mô phỏng 20 review entries có chữ ký của `Nguyễn Trọng Hùng (MSV: 2A202603147)`.
- **Decision Policy:**
  - Trả về `REWORK` nếu phát hiện $>65\%$ ảnh trong top $B$ bị lỗi nặng (báo động phần cứng/môi trường cần thu thập lại).
  - Trả về `GO` khi luồng triage hoàn tất cách ly được các lỗi và số lượng khuyết tật nằm trong ngưỡng quản trị an toàn.

## 08 · Reproduce & tests

```bash
# 1. Chạy preflight kiểm tra môi trường và tính toàn vẹn (0 FAIL)
python -m tools.preflight

# 2. Chạy baseline
python -m src.main --track t02 --pipeline src.examples.random_baseline --output out/baseline --run-name baseline --offline --seed 42

# 3. Chạy đường ống PoC chính của nhóm AA1
python -m src.main --config configs/lab.yaml --output out/poc --run-name poc --offline --seed 42

# 4. Chạy bộ unit tests của nhóm (5/5 passed)
python -m pytest tests/test_t02_aa1.py -v
```

- **Kiểm chứng lại ngày 2026-11-15:** `.venv\Scripts\python.exe -m pytest -ra` trên Python 3.11 / Windows: **64 passed, 39 skipped, 0 failed**. Các ca skipped cần ground truth riêng của giảng viên; chưa kiểm chứng lại các metric eval bằng lượt chạy này.
- **Môi trường lần chạy PoC ban đầu:** Python 3.12 · Windows 11 · Offline guard active · Seed 42.

### QA bổ sung ngày 2026-11-15

- Bổ sung với hỗ trợ Codex theo yêu cầu của thành viên QA; thay đổi được ghi bằng danh tính Git `NgoThiMinhQuang <minhquang17012005@gmail.com>`.
- `tests/test_t02_review_gate.py` có 12 ca: edit/reject chỉ thay action của ảnh được review; approve không áp override; prediction gốc, score và loại lỗi được giữ nguyên; audit lưu actor, timestamp, before/after và lý do, đồng thời giữ các dòng cũ.
- Kiểm tra từ chối review thiếu người thực hiện hoặc có decision không hợp lệ; khi chưa có file review thì giữ prediction ban đầu.
- Kiểm tra biên chính sách với B=20: 0/3 ảnh nghi lỗi nặng → HOLD, 4/13 → GO, 14/20 → REWORK. Score 0,60 được tính là nghi lỗi nặng; 0,59 không được tính. Đây là kiểm tra hành vi code, không chứng minh batch đã an toàn để release.
- Phát hiện 170 file fixture lệch SHA-256 do checkout CRLF. Sau khi chỉ chuyển CRLF về LF, tất cả khớp hash đã có trong manifest. Commit `6179ef1` thêm `.gitattributes` để giữ LF khi clone trên Windows; không thay hash trong manifest.
- Dữ liệu reviewer trong tests là giả lập, không phải bằng chứng đã review ảnh thật. Lượt QA này không đánh giá lại Recall/Precision và không thay đổi số liệu metrics có sẵn.

## 09 · Limitations & ethics

- **Rủi ro pháp lý & PII:** Dữ liệu synthetic CC0 không chứa khuôn mặt hoặc biển số thật; khi áp dụng lên dữ liệu thực tế (BDD100K) cần kích hoạt thêm mô hình làm mờ khuôn mặt/biển số (T07 Redaction) trước khi release.
- **Điều chưa biết:** Nếu môi trường thời tiết có tuyết trắng dày đặc (snow cover), đặc trưng bão hòa sáng có thể bị nhiễu tương tự lóa đèn.
- **Kế hoạch cải tiến:** Tích hợp mô hình nhẹ ONNX/YOLO nano offline để khoanh vùng ROI biển báo giao thông trước khi tính độ nét cục bộ.

## 10 · Team contribution

**Bảng 2 · Individual contribution evidence** (đối chiếu với `git shortlog -sne --all` và `reports/team_contributions.csv`)

| Học viên | Git author/email | Module / vai trò | Commit SHA / diff chứng minh | Trình bày? |
|---|---|---|---|:---:|
| Nguyễn Trọng Hùng (2A202603147) | Nguyễn Trọng Hùng <ngtronghung004@gmail.com> | Lead / Integrator (`src/pipeline.py`, `configs/lab.yaml`, `run.ps1`) | `demo-180m` / `final-24h` | Có |
| Nguyễn Tấn Dũng (2A202603031) | Nguyễn Tấn Dũng <scarlest2576@gmail.com> | Data & Fixtures (`fixtures/`, `tools/verify_manifests.py`) | `demo-180m` / `final-24h` | Không |
| Bùi Kim Trại (2A202603176) | Bùi Kim Trại <buikimtrai2k5@gmail.com> | Core Algorithm (`src/pipeline.py`, `src/common/image_ops.py`) | `demo-180m` / `final-24h` | Không |
| Ngô Thị Minh Quang (2A202603146) | NgoThiMinhQuang <minhquang17012005@gmail.com> | QA bổ sung: `tests/test_t02_review_gate.py`, `.gitattributes`; kết quả tại mục 08 | `6179ef1`; commit QA tra bằng `git log -- tests/test_t02_review_gate.py` | Không |
| Nguyễn Thị Hương Giang (2A202603233) | Nguyễn Thị Hương Giang <nthgiang0511@gmail.com> | Human Review & Report (`reports/group_report.md`, `reports/metric_contract.md`) | `demo-180m` / `final-24h` | Không |

---

*Nhóm AA1 — Ký duyệt: Nguyễn Trọng Hùng - MSV: 2A202603147 (QA Lead)*
