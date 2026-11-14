# Metric contract (khai báo bắt buộc — chốt ở phút 30, trước khi chạy eval)

> Các metric chuẩn đã được cài trong `src/metrics/tracks.py`. File này là nơi nhóm **cam kết** cách dùng chúng.
> Không đổi testset, threshold hay trọng số sau khi đã thấy kết quả eval.

| Mục | Khai báo của nhóm |
|---|---|
| Track | T09 · Multi-Market Privacy Decision Gate (bài cá nhân) |
| Primary metric (tên đúng như evaluator in ra) | `Critical-miss Rate` — chỉ hợp lệ khi guardrail `False HOLD rate` ≤ 0.5 PASS |
| Tăng tốt hay giảm tốt? | lower |
| Đơn vị đánh giá (image / region / pair / release / batch / case …) | case (1 file `cases/CASE-XX.json` = 1 dự án × 1 thị trường) |
| Công thức + numerator / denominator | số case gold ≠ GO mà pred = GO / số case gold ≠ GO. Guardrail: số case gold = GO mà pred ≠ GO / số case gold = GO |
| Cách ghép prediction ↔ GT (IoU? id? tolerance?) | ghép theo `case_id`; case thiếu trong `decisions.csv` tính là GO (worst case) |
| Candidate pool cố định | 12 case trong `fixtures/t09_privacy_gate/cases/` (sha256 khớp `manifest.csv`) |
| Review budget B / K | B = 12 (toàn bộ case): người phụ trách pháp lý ký duyệt mọi case, HOLD xếp trước |
| Seed | 42 (engine deterministic, không dùng random) |
| Threshold policy (chọn trên dev như thế nào) | Không có threshold học được. Rule viết tay trong `configs/policy/t09_policy.yaml` (version `t09-1.0`), có nguồn điều luật; ngưỡng duy nhất là retention > 365 ngày → REWORK (chính sách nội bộ). `as_of_date = 2026-11-14`. Precedence HOLD > REWORK > GO |
| Eval split (không dùng để tune) | `split: eval` = CASE-09..12 (số chính thức). `--split all` chỉ để tự kiểm |
| Chỉ số lỗi xấu (miss / false alarm / false reject) | critical miss (case rủi ro bị GO) là lỗi xấu nhất; false HOLD (case an toàn bị chặn) là chi phí phụ |
| Slices sẽ báo cáo (≥2) | theo `gold_decision` (GO / HOLD / REWORK — evaluator in sẵn) và theo market (EU, VN, US-CA, SG, IN); báo từng case vì N rất nhỏ |
| Cách báo độ bất định khi N nhỏ (Wilson CI / bootstrap) | N_eval = 4 → không báo CI có ý nghĩa; báo bảng từng case + split=all (N = 12) làm self-check |
| Ngày giờ chốt + người chốt | 2026-11-14, Chu Thien Phu — rule chốt ở commit `bd8d135`, trước khi có GT (repo học viên không có `gt/`) |

Khai báo trung thực: khi viết rule, tôi đã đọc **input** của cả 12 case (kể cả CASE-09..12), nhưng không đọc gold decision
nào. Không có số eval nào được dùng để chỉnh rule.

Nếu baseline = 0 thì ghi rõ "baseline = 0" thay vì phần trăm cải thiện.
