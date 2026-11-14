# Metric contract (khai báo bắt buộc — chốt ở phút 30, trước khi chạy eval)

> Các metric chuẩn đã được cài trong `src/metrics/tracks.py`. File này là nơi nhóm **cam kết** cách dùng chúng.
> Không đổi testset, threshold hay trọng số sau khi đã thấy kết quả eval.

| Mục | Khai báo của nhóm |
|---|---|
| Track | T02 · Raw QC Triage |
| Primary metric (tên đúng như evaluator in ra) | Defect Recall@B |
| Tăng tốt hay giảm tốt? | higher |
| Đơn vị đánh giá (image / region / pair / release / batch / case …) | image |
| Công thức + numerator / denominator | GT defects in top-B / GT defects |
| Cách ghép prediction ↔ GT (IoU? id? tolerance?) | image_id |
| Candidate pool cố định | 96 ảnh (fixtures/t02_raw_qc/images.csv) |
| Review budget B / K | B = 20 |
| Seed | 42 |
| Threshold policy (chọn trên dev như thế nào) | Cân chỉnh feature weights (blur, dark, glare, compression) trên split dev (60%), chuẩn hoá theo slice light/camera_id, không dùng split eval để tune. |
| Eval split (không dùng để tune) | eval (40% theo cảnh gốc) |
| Chỉ số lỗi xấu (miss / false alarm / false reject) | False alarm in top-B trên clean images (đặc biệt slice light=night) |
| Slices sẽ báo cáo (≥2) | light (day, dusk, night); camera_id (cam_A, cam_B) |
| Cách báo độ bất định khi N nhỏ (Wilson CI / bootstrap) | Wilson CI 95% cho Defect Recall@B |
| Ngày giờ chốt + người chốt | 2026-11-14 14:40 (VN) · Nguyễn Trọng Hùng - MSV: 2A202603147 - Email: ngtronghung004@gmail.com (QA Lead, Nhóm AA1) |

Nếu baseline = 0 thì ghi rõ "baseline = 0" thay vì phần trăm cải thiện.
