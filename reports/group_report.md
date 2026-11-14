# Group Report — Day 06 Data Lab (Field-to-Release PoC)

> Bài cá nhân. Số liệu quyết định lấy từ file do script sinh ra (`out/*/decisions.csv`, `reports/review_queue.csv`,
> `reports/decision_log.csv`). Repo học viên không có `gt/` nên **chưa có** `reports/metrics_*.json` và
> `table1_baseline_vs_poc.md`: các file này sinh bằng lệnh ở §05 khi giảng viên cài overlay. Không có số metric nào gõ tay.

## 00 · Header

| Mục | Giá trị |
|---|---|
| Group ID | 2A202603114 (cá nhân) |
| Challenge | T09 · Multi-Market Privacy Decision Gate |
| Thành viên + vai trò | 1. Chu Thien Phu — tất cả vai trò (integrator, policy engine, QA/test, legal reviewer, report) |
| Git URL | https://github.com/chuphu2004/K5-DAY6-L2-ChuThienPhu-2A202603114-DataGovernanceAndPrivacy |
| Tag `demo-180m` (commit) | chưa tạo — tạo sau khi có kết quả eval với ground truth |
| Tag `final-24h` (commit) | chưa tạo — tạo sau khi có kết quả eval với ground truth |
| Deadline (giờ VN) | 23:59 ngày 14/11/2026 (12h đêm) |

## 01 · Problem statement

- **Ai bị ảnh hưởng:** người đi bộ, tài xế, hành khách bị quay trong video ADAS (không biết mình bị thu thập); công ty
  chịu phạt và rủi ro uy tín nếu dữ liệu được dùng sai luật ở một thị trường.
- **Điểm nghẽn:** mỗi dự án × thị trường phải được legal duyệt thủ công; checklist kiểu "có consent là xong" bỏ sót
  chuyển dữ liệu xuyên biên giới, DPIA, hạn lưu trữ và khác biệt giữa các luật (VN không có "lợi ích hợp pháp").
- **Đầu vào → đầu ra:** 12 hồ sơ case JSON + rule file YAML có version/nguồn → `decisions.csv`
  (`case_id, decision ∈ {GO, HOLD, REWORK}, reason_codes`) + checklist từng rule + audit log + chữ ký reviewer.
- **Tiêu chí (chốt trước eval):** HOLD = rủi ro nghiêm trọng / thiếu căn cứ pháp lý / chuyển dữ liệu không có cơ chế /
  chưa DPIA khi bắt buộc / có điểm mơ hồ / có thể có trẻ em / thị trường không có rule. REWORK = thiếu sót sửa được
  (notice, consent không hợp lệ, retention, raw PII trên cloud, không mã hoá). GO = không rule nào vi phạm.
- **Giả định cần DPO/legal xác nhận:** số điều luật VN (Luật 91/2025, NĐ 356/2025) lấy từ bản dịch, `confidence: medium`;
  ngưỡng retention 365 ngày là chính sách nội bộ; rule trẻ em là biện pháp thận trọng nội bộ, không dựa trên một luật
  đang có hiệu lực ở mọi thị trường.

## 02 · Data & provenance

| Split | N | Nguồn / link | License | Synthetic? |
|---|---|---|---|---|
| dev | 8 (CASE-01..08) | `fixtures/t09_privacy_gate/cases/` (tools/make_fixtures.py, seed 42) | CC0-1.0 | có |
| eval / heldout | 4 (CASE-09..12) | như trên | CC0-1.0 | có |

- Schema: mỗi case có `market, data_types, data_subjects, lawful_basis, consent.{obtained, granular, withdrawable,
  record_available}, notice_given, storage.{raw_retained, location, encryption_at_rest}, transfer.{cross_border,
  destination, mechanism, transfer_impact_assessment}, retention_days, dpia_done, minors_possible, ambiguity_notes`;
  vài case có thêm `lia_done` / `li_assessment_done` (field thiếu được đọc là null).
- Seed: 42 · Split do giảng viên cố định theo case id.
- `manifest.csv` verified (sha256): **có** — `python -m tools.verify_manifests` → 14 manifests, 0 failing.
  Vì `rules/policy_example.yaml` bị khoá hash, rule của tôi nằm ở `configs/policy/t09_policy.yaml` (bản mở rộng từ file mẫu).
- Dữ liệu thật: không dùng (đề không yêu cầu).

## 03 · Research & design

- **Thiết kế:** policy engine offline theo gợi ý đề — rule DSL đơn giản (dotted field path + so sánh, `and/or/not`),
  precedence HOLD > REWORK > GO, mọi quyết định kèm rule id + nguồn. 23 rule cho EU, VN, US-CA, SG, IN + rule chung.
- **Vì sao rule-based thay vì model:** N = 12, quyết định phải giải thích được bằng điều luật và kiểm toán được;
  một model học từ 8 case dev không có giá trị pháp lý.
- **Data flow:**
  `cases/*.json + t09_policy.yaml → load (verify sha256, validate rule có source) → process (rule theo market,
  effective_date) → rank (queue 12 case, HOLD trước) → contact_sheet.html (facts + rule + nguồn) → reviewer
  export CSV → review (approve/edit/escalate + audit log) → decisions.csv + checklist.csv + decision.json`
- **An toàn của DSL:** biểu thức `when` được parse AST và chỉ cho phép so sánh/boolean/tên/hằng; cấm gọi hàm và
  truy cập `_…` (có test). `eval` chạy với builtins rỗng.
- **effective_date:** rule có `effective_date` > `as_of_date` chỉ ghi vào cột `upcoming`, không đổi quyết định
  (ví dụ DPDP Ấn Độ, nghĩa vụ cốt lõi từ 13/05/2027).
- **Trade-offs:** rule viết tay dễ thiếu (thị trường lạ → mặc định HOLD `AMBIGUOUS_NEEDS_LEGAL`); ưu tiên không bỏ sót
  rủi ro hơn là giảm false HOLD.
- Thành phần offline: không có model/weights.

## 04 · Baseline vs PoC

- **Baseline 1 (đề yêu cầu, cố tình sai):** "consent obtained → GO, còn lại HOLD" — `src/baseline_t09.py`, commit `e2e511a`.
- **Baseline 2 (tầm thường):** HOLD tất cả — `src/baseline_t09_allhold.py`, commit `e2e511a`.
- **PoC:** policy engine `src/pipeline.py` + `configs/policy/t09_policy.yaml` (`t09-1.0`), commit `bd8d135`.
- Cùng pool 12 case / cùng seed 42 / cùng split eval: xác nhận.

**Bảng quyết định từng case** (sinh từ `out/baseline/`, `out/baseline_allhold/`, `out/poc/decisions.csv`):

| Case | Split | Market | Consent-only | All-HOLD | PoC auto | PoC final (reviewed) | Reason codes (PoC) | Upcoming |
|---|---|---|---|---|---|---|---|---|
| CASE-01 | dev | VN | HOLD | HOLD | HOLD | HOLD | NO_LAWFUL_BASIS | — |
| CASE-02 | dev | EU | GO | HOLD | HOLD | HOLD | XBORDER_NO_MECHANISM | — |
| CASE-03 | dev | VN | GO | HOLD | REWORK | REWORK | RETENTION_UNBOUNDED; RAW_PII_IN_CLOUD; CONSENT_INVALID | — |
| CASE-04 | dev | EU | HOLD | HOLD | HOLD | HOLD | NO_LAWFUL_BASIS; DPIA_MISSING | — |
| CASE-05 | dev | US-CA | HOLD | HOLD | REWORK | REWORK | NOTICE_MISSING | — |
| CASE-06 | dev | SG | HOLD | HOLD | GO | GO | — | — |
| CASE-07 | dev | VN | GO | HOLD | HOLD | HOLD | XBORDER_NO_IMPACT_ASSESSMENT | — |
| CASE-08 | dev | EU | HOLD | HOLD | HOLD | HOLD | AMBIGUOUS_NEEDS_LEGAL; NO_LAWFUL_BASIS | — |
| CASE-09 | eval | IN | GO | HOLD | HOLD | HOLD | AMBIGUOUS_NEEDS_LEGAL; MINORS | R-IN-CREC:CONSENT_RECORD_MISSING@2027-05-13 |
| CASE-10 | eval | EU | HOLD | HOLD | GO | GO | — | — |
| CASE-11 | eval | US-CA | HOLD | HOLD | HOLD | HOLD | AMBIGUOUS_NEEDS_LEGAL | — |
| CASE-12 | eval | VN | HOLD | HOLD | HOLD | HOLD | RETENTION_EXCESSIVE; RAW_PII_IN_CLOUD; NO_ENCRYPTION; NO_LAWFUL_BASIS | — |

Consent-only cho GO 4 case mà PoC xác định có rủi ro (CASE-02, 03, 07, 09) và chặn 2 case PoC cho GO (CASE-06, 10).

**Bảng 1 · Baseline vs PoC** — chờ ground truth: dán output của
`python -m src.compare reports/metrics_baseline.json reports/metrics_poc.json` sau khi có overlay `gt/`.
Chưa có GT nên không điền số nào ở đây.

| Metric (unit) | Baseline | PoC | Δ & chú thích |
|---|---|---|---|
| Primary: Critical-miss Rate (lower) | chờ GT (script) | chờ GT (script) | split=eval, N=4 |
| Guardrail: False HOLD rate ≤ 0.5 | chờ GT (script) | chờ GT (script) | All-HOLD: critical-miss = 0 nhưng FAIL guardrail theo định nghĩa |
| Reason-code match (risky) | chờ GT (script) | chờ GT (script) | |
| Runtime / 12 case | 0.059 s | 0.122 s | `run_info.json`, CPU x86_64, Python 3.11.0rc1 |

## 05 · Evaluation protocol

- Primary: Critical-miss Rate = case gold ≠ GO bị pred GO / case gold ≠ GO; guardrail False HOLD rate ≤ 0.5
  (xem `reports/metric_contract.md`). Đơn vị: case. Case thiếu = GO.
- Không có threshold học; rule + `as_of_date` chốt ở commit `bd8d135` trước khi có GT.
- Độ bất định: N_eval = 4 → báo từng case, không báo CI.
- Lệnh evaluate (cần overlay giảng viên):

```bash
python -m src.evaluate --track t09 --pred out/baseline/decisions.csv --run-name baseline --out reports/metrics_baseline.json
python -m src.evaluate --track t09 --pred out/poc/decisions.csv --run-name poc --out reports/metrics_poc.json
python -m src.compare reports/metrics_baseline.json reports/metrics_poc.json --out reports/table1_baseline_vs_poc.md
python -m src.evaluate --track t09 --pred out/baseline_allhold/decisions.csv --run-name allhold --out reports/metrics_allhold.json
```

## 06 · Result slices

| Slice | N | Consent-only | PoC | Ghi chú |
|---|---|---|---|---|
| Market EU (01-dev: 02, 04, 08; eval: 10) | 4 | 3 HOLD, 1 GO (CASE-02) | 3 HOLD, 1 GO (CASE-10) | baseline GO nhầm case chuyển dữ liệu không cơ chế, HOLD nhầm case đủ điều kiện |
| Market VN (01, 03, 07, 12) | 4 | 2 HOLD, 2 GO | 3 HOLD, 1 REWORK | VN không có lợi ích hợp pháp; chuyển dữ liệu cần hồ sơ đánh giá tác động |
| Market US-CA / SG / IN (05, 06, 09, 11) | 4 | 3 HOLD, 1 GO | 2 HOLD, 1 REWORK, 1 GO | CCPA không có lawful basis → baseline HOLD CASE-05 vì lý do sai |
| Slice theo gold_decision | — | chờ GT (script) | chờ GT (script) | evaluator in sẵn |

- **Failure case 1 — kết luận hợp pháp chỉ dựa vào consent (CASE-02, EU).** Metadata: `consent.obtained/granular/
  withdrawable/record_available = true`, nhưng `transfer.cross_border = true`, `destination = "non-adequate third
  country"`, `mechanism = null`. Root cause: checklist consent-only không xét GDPR Chương V (Đ.44–49); consent của
  người bị quay không thay thế cơ chế chuyển dữ liệu. Baseline: GO → PoC: HOLD `XBORDER_NO_MECHANISM` (rule `R-XB-01`).
- **Failure case 2 — bỏ sót rủi ro chuyển dữ liệu xuyên biên giới ở VN (CASE-07).** Metadata: consent hợp lệ đủ 4
  cờ, `cross_border = true`, `destination = "SG"`, `mechanism = "unknown"`, `transfer_impact_assessment = false`.
  Root cause: Luật 91/2025 Đ.21 + NĐ 356/2025 yêu cầu hồ sơ đánh giá tác động chuyển dữ liệu ra nước ngoài, độc lập với
  consent. Baseline: GO → PoC: HOLD `XBORDER_NO_IMPACT_ASSESSMENT` (rule `R-VN-02`).
- **Case khó / tranh luận — CASE-09 (IN).** DPDP chưa có hiệu lực (13/05/2027) nên thiếu bằng chứng consent chỉ là
  `upcoming`, không phạt. PoC vẫn HOLD vì `minors_possible = true` (rule thận trọng nội bộ) và `ambiguity_notes` khác
  rỗng. Reviewer giữ HOLD. Nếu gold là GO thì đây là false HOLD có chủ đích; guardrail vẫn PASS nếu CASE-10 là GO
  (1/2 = 0.5 ≤ 0.5).
- **Latency:** 0.122 s cho 12 case (~10 ms/case) trên Linux 6.8 x86_64, Python 3.11.0rc1.

## 07 · Human & decision

- **Review queue:** `out/poc/review_queue.csv` + `out/poc/contact_sheet.html`, B = 12 (mọi case), xếp theo
  điểm = mức độ (HOLD 2 / REWORK 1 / GO 0) + 0.5 nếu cần legal review. Mỗi thẻ hiện facts của case, rule vi phạm,
  nguồn điều luật, `upcoming`, ghi chú mơ hồ.
- **Override + audit:** reviewer chọn `approve` (giữ), `edit/reject` + `override_value` GO/HOLD/REWORK (đổi),
  `escalate` (→ HOLD). Mọi quyết định tự động và mọi lượt review ghi vào `out/poc/audit_log.jsonl` (append-only,
  có actor, before/after, lý do). Thiếu `reviewer` hoặc override sai giá trị → pipeline dừng exit 2 (có test).
- **Bằng chứng thực tế:** lần export đầu có CASE-09 = `reject` nhưng trống override → pipeline dừng exit 2, không áp
  quyết định nào sau case lỗi; tôi sửa thành `approve`, sửa ghi chú CASE-10 bị dán nhầm, chạy lại → exit 0, 12/12 case
  có chữ ký "Chu Thiên Phú" (`reports/review_queue.csv`). Audit log giữ cả dòng của lần chạy lỗi (13 dòng review).
- **Decision policy:** quyết định cấp release = mức nặng nhất trong các case → `HOLD`, `reason_code = GATE_HOLD`,
  owner "Chu Thien Phu (Privacy Lead)", "8 HOLD, 2 REWORK, 2 GO; 0 case(s) still awaiting legal sign-off"
  (`reports/decision_log.csv`).
- **Khi nào không tự động release:** mọi case đều cần chữ ký người; engine chỉ đề xuất. Case mơ hồ, thị trường
  không có rule, hoặc rule `needs_legal_review` → HOLD chờ DPO/legal.

## 08 · Reproduce & tests

```bash
python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m src.main --config configs/lab.yaml --track t09 --output out/poc --run-name poc --offline --seed 42
.venv/bin/python -m src.main --track t09 --pipeline src.baseline_t09 --output out/baseline --run-name baseline --offline --seed 42
.venv/bin/python -m src.main --track t09 --pipeline src.baseline_t09_allhold --output out/baseline_allhold --run-name baseline_allhold --offline --seed 42
# review: điền out/poc/review_queue_reviewed.csv (hoặc reports/review_queue.csv) rồi chạy lại lệnh poc
.venv/bin/python -m pytest -q
```

- Output của `pytest`: `57 passed, 39 skipped` (skip = test cần `gt/`). Test T09 (`tests/test_t09_pipeline.py`, 10 test):
  E2E + 2 failure mode + tái lập cùng seed; DSL chặn code (3 biểu thức); rule `effective_date` tương lai chỉ là
  upcoming; thị trường không có rule → HOLD; override được áp + ghi audit; override sai → exit 2; 2 baseline.
- Máy: Linux 6.8.0-124-generic x86_64 · Python 3.11.0rc1 · git sha: xem tag `final-24h`.

## 09 · Limitations & ethics

- **Không phải tư vấn pháp lý.** Hệ thống **không** chứng nhận "đạt GDPR / luật Việt Nam"; nó là công cụ hỗ trợ rà soát,
  quyết định cuối thuộc DPO/legal. Số điều luật VN cần đối chiếu văn bản gốc (`needs_legal_review: true`).
- PII / license: fixture synthetic CC0, không có người thật.
- Rủi ro: rule thiếu → có thể GO nhầm case có rủi ro chưa được mô hình hoá (ví dụ dữ liệu sinh trắc học, quyền
  opt-out CCPA, nghĩa vụ xóa dữ liệu). Hồ sơ case khai sai → engine kết luận sai; engine không kiểm chứng sự thật.
- False alarm: rule thận trọng (trẻ em, mơ hồ) có thể chặn case hợp lệ; chấp nhận vì critical miss nặng hơn.
- Scale 10×: runtime không thành vấn đề (~10 ms/case); nút thắt là thời gian người duyệt → cần ưu tiên queue,
  chỉ bắt buộc ký tay case HOLD/REWORK + mẫu ngẫu nhiên case GO.
- Cải tiến (+24h): đối chiếu CA/VN/EU chi tiết hơn, bổ sung deletion requirement, version `effective_date` cho mọi rule,
  test hồi quy cho từng rule.

## 10 · Team contribution

**Bảng 2 · Individual contribution evidence** (đối chiếu với `git shortlog -sne --all` và `reports/team_contributions.csv`)

| Học viên | Git author/email | Module / vai trò | Commit SHA / diff chứng minh | Trình bày? |
|---|---|---|---|---|
| Chu Thien Phu | Chu Thien Phu <chuphu2004@gmail.com> | Toàn bộ (bài cá nhân): policy engine, baselines, tests, review, report | `bd8d135`, `e2e511a`, `56965ad` + commit report | có |

Các commit của `loversky02` và `Tin Duong` trong lịch sử là của starter repo (giảng viên), không phải đóng góp bài làm.

## 11 · References

| URL | Ngày xem | 1–2 dòng ý nghĩa (không chép nguyên văn) |
|---|---|---|
| https://eur-lex.europa.eu/eli/reg/2016/679/oj | 2026-11-14 (nguồn trích trong file mẫu) | GDPR: căn cứ pháp lý Đ.6, consent Đ.7, DPIA Đ.35, chuyển dữ liệu Chương V |
| https://thuvienphapluat.vn/van-ban/Bo-may-hanh-chinh/Luat-Bao-ve-du-lieu-ca-nhan-2025-so-91-2025-QH15-625628.aspx | 2026-11-14 (nguồn trích trong file mẫu) | Luật 91/2025: không có lợi ích hợp pháp; đánh giá tác động xử lý và chuyển dữ liệu ra nước ngoài |
| `docs/tracks/T09.md` §8 | 2026-11-14 | CCPA không có lawful basis; DPDP từ 13/05/2027; tách luật hiện hành / sắp hiệu lực |

---

**Bảng 3 · Checklist chốt khi nộp**

- [ ] Link repo (có) và tag cuối cùng (chưa tạo) trong report mục 00; input mẫu không chứa PII thật.
- [x] Đúng 1 lệnh run, 1 lệnh evaluate, 1 lệnh tests; không cần download khi chạy.
- [ ] Có baseline/PoC metrics (chờ overlay `gt/`), [x] ≥1 failure case, [x] reviewer evidence, [x] decision log.
- [x] Có license/source provenance, data splits, seed, offline environment, GT/eval N.
- [x] Mỗi thành viên có ≥1 commit thực chất và được nêu minh bạch trong bảng trên.
