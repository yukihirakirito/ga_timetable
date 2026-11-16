# Đặc tả bài toán & các quyết định đã chốt

Tài liệu gốc của project. Mọi thay đổi về bài toán phải cập nhật ở đây trước khi code.

## 1. Bài toán

University Course Timetabling (NP-hard, quy về tô màu đồ thị). Xếp lịch một **học kỳ** cho Khoa CNTT:
GA quyết định **giảng viên** cho từng lớp-môn và **thời điểm** cho từng buổi học; phòng được gán khi decode.

## 2. Thuật ngữ

| Thuật ngữ | Nghĩa |
|---|---|
| Học kỳ (`semester`) | Khoảng thời gian thật, 18 tuần = 15 tuần học + 3 tuần thi |
| Kỳ đào tạo (`term_no`) | Lớp đang ở kỳ thứ mấy của chương trình (1..6) |
| Tiết | 45 phút, đơn vị thời gian nhỏ nhất, 12 tiết/ngày |
| Ca | Khung giờ của TKB: ca sáng (tiết 1–6), ca chiều (tiết 7–12) |
| Buổi học | n tiết liền kề (2 ≤ n ≤ 5) của một lớp-môn, nằm trọn trong một ca |
| Lớp-môn (`course_section`) | Một lớp sinh viên học một môn trong học kỳ |
| Sinh viên (`student`) | Thuộc đúng một lớp; học **toàn bộ** lớp-môn của lớp mình trong học kỳ (không miễn môn) |
| Học thêm (`extra_enrollment`) | Sinh viên đăng ký thêm lớp-môn của **lớp khác** (học lại môn kỳ trước, học ghép) |
| Sĩ số lớp-môn | Số sinh viên của lớp + số sinh viên học thêm lớp-môn đó |
| Nhóm sinh viên | Các sinh viên có cùng tập lớp-môn (lớp mình + phần học thêm). Chỉ sinh viên có học thêm mới tạo nhóm riêng |

## 3. Thời gian

- Ngày bắt đầu, ngày kết thúc học kỳ và danh sách ngày lễ: chọn trên giao diện.
  Ngày bắt đầu phải là **Thứ 2**; khoảng thời gian phải đủ 18 tuần (DB kiểm tra bằng CHECK).
- Học 6 ngày/tuần (Thứ 2 – Thứ 7). 3 tuần thi: **chưa xử lý**, chỉ chừa trống.
- Tiết 45', nghỉ 5' giữa các tiết.

| Tiết | Giờ | Tiết | Giờ |
|---|---|---|---|
| 1 | 07:00 – 07:45 | 7 | 12:30 – 13:15 |
| 2 | 07:50 – 08:35 | 8 | 13:20 – 14:05 |
| 3 | 08:40 – 09:25 | 9 | 14:10 – 14:55 |
| 4 | 09:30 – 10:15 | 10 | 15:00 – 15:45 |
| 5 | 10:20 – 11:05 | 11 | 15:50 – 16:35 |
| 6 | 11:10 – 11:55 | 12 | 16:40 – 17:25 |

## 4. Tín chỉ → lịch học

1 TC = 15 tiết. Bảng quy đổi là **cấu hình** (`credit_rules`), mặc định:

| TC | Tổng tiết | Tiết/buổi | Số buổi | Buổi/tuần | Số tuần học |
|---|---|---|---|---|---|
| 1 | 15 | 3 | 5 | 1 | 5 |
| 2 | 30 | 3 | 10 | 1 | 10 |
| 3 | 45 | 3 | 15 | 2 | 8 |
| 4 | 60 | 4 | 15 | 2 | 8 |
| 5 | 75 | 5 | 15 | 2 | 8 |

Quy tắc kiểm tra: tiết/buổi ∈ [2, 5]; TC ≥ 4 ⇒ tiết/buổi ≥ 3; `số buổi = ceil(tổng tiết / tiết_mỗi_buổi)`,
buổi cuối nếu ngắn hơn vẫn phải ≥ 2 tiết.

**Cách A:** mỗi lớp-môn có số buổi/tuần nguyên, học từ tuần 1 theo đúng tuần mẫu cho đến khi đủ số buổi thì dừng.
Hệ quả đã chấp nhận: lịch dồn về nửa đầu kỳ.

## 5. Ràng buộc (danh sách chính thức)

**Cứng**

| Mã | Nội dung |
|---|---|
| H1 | Một lớp sinh viên không học 2 buổi chồng tiết |
| H2 | Một giảng viên không dạy 2 buổi chồng tiết |
| H3 | Một phòng không chứa 2 buổi chồng tiết |
| H4 | Phòng đúng loại và đủ sức chứa (theo **sĩ số lớp-môn**, tính cả sinh viên học thêm) |
| H5 | Không xếp vào khung giờ giảng viên bận (`UNAVAILABLE`) |
| H6 | Các buổi trong tuần của cùng một lớp-môn ở các ngày khác nhau |
| H7 | Giảng viên đúng chuyên môn (đảm bảo bằng miền giá trị của gen) |
| H8 | Buổi học nằm trọn trong một ca, không vắt qua giờ nghỉ trưa |
| H9 | Lớp-môn học đủ số buổi trước hết tuần 15 (tính cả học bù) |
| H10 | Một sinh viên không học 2 buổi chồng tiết (gồm cả lớp-môn học thêm). *Chốt 2026-11-16, cài ở M8* |

**Mềm** (có trọng số)

| Mã | Nội dung |
|---|---|
| S1 | Lịch sinh viên gọn: ít khoảng trống trong ca, ít ngày phải lên trường |
| S2 | Các buổi trong tuần của một môn rải đều (cách nhau ≥ 1 ngày) |
| ~~S3~~ | *Đã bỏ* (lớp học cả sáng lẫn chiều trong ngày không bị phạt). Các mã khác giữ nguyên số |
| S4 | Giảm số ngày giảng viên phải lên trường |
| S5 | Tôn trọng khung giờ ưu tiên của giảng viên (`PREFERRED`) |
| S6 | Cân bằng tải giữa các giảng viên |
| S7 | Một lớp-môn học cố định một phòng |
| S8 | Không vượt số tiết tối đa/tuần của giảng viên |

Lớp sinh viên **không** bị cố định học sáng hoặc chiều.

**Cách đo** (cài đặt ở `solver/src/solver/evaluate.py`; trọng số mặc định trong ngoặc)

Chỉ dùng điểm phạt: `fitness = 10 000 × Σ vi phạm cứng + Σ wᵢ × vi phạm mềmᵢ`, càng nhỏ càng tốt, 0 là hoàn hảo.
Phạt cứng 10 000 do người dùng chốt; nếu tổng phạt mềm của một lịch vượt 10 000 thì một lịch có
1 vi phạm cứng có thể thắng lịch hợp lệ, cần theo dõi khi chạy GA.

| Mã | Đơn vị đo |
|---|---|
| H1, H2 | Số tiết bị trùng (một tiết có k buổi tính k − 1) |
| H3 | Số buổi không gán được phòng (bước gán phòng không bao giờ xếp chồng) |
| H4 | Luôn 0 do gán phòng đã lọc loại và sức chứa; giữ để kiểm tra chéo |
| H5 | Số tiết dạy rơi vào giờ bận |
| H6 | Số buổi thừa trong cùng một ngày của một lớp-môn |
| H10 | Σ trên các nhóm sinh viên: số tiết bị trùng giữa các buổi của nhóm mà ít nhất một buổi thuộc lớp-môn học thêm (trùng giữa hai buổi cùng lớp đã tính ở H1). **Không** nhân số sinh viên trong nhóm |
| S1 (1) | Tiết trống kẹp giữa các buổi trong cùng ca + số ngày lớp phải lên trường |
| S2 (5) | Số cặp ngày liền kề có buổi của cùng lớp-môn |
| S4 (1) | Số (giảng viên, ngày) có dạy |
| S5 (1) | Số tiết ưu tiên của giảng viên không được xếp dạy |
| S6 (0.5) | Σ \|tải − tải mục tiêu\|, mục tiêu = tải tối đa × (tổng tải ÷ tổng tải tối đa) |
| S7 (1) | Σ (số phòng khác nhau của lớp-môn − 1) |
| S8 (5) | Σ số tiết vượt tải tối đa |

## 6. Thuật toán

**Giai đoạn 1: GA xếp tuần mẫu**

- Nhiễm sắc thể: `[ giảng viên[lớp-môn] | (thứ, tiết bắt đầu)[buổi] ]`.
  Độ dài buổi suy ra từ TC, không do GA chọn. Miền giá trị đã loại sẵn vị trí vi phạm H7, H8.
- Phòng không mã hoá: gán khi decode theo từng ngày (`solver/src/solver/rooms.py`):
  1. tham lam kiểu interval partitioning: buổi **ít phòng dùng được nhất** trước, cùng mức thì theo giờ bắt đầu;
     giữ phòng cũ của lớp-môn nếu rảnh (S7), không thì phòng nhỏ nhất đủ chỗ (best-fit); kiểm tra rảnh bằng `owner[phòng][tiết]`;
  2. kẹt thì **tìm đường tăng** (như ghép cặp hai phía): đẩy buổi đang chặn sang phòng khác, sâu 2 tầng, tối đa 5 lần đẩy.
  Bản đầu (chỉ xếp theo giờ bắt đầu) phạt oan lịch có cách xếp phòng: DSatur giữ được phòng cho mọi buổi
  nhưng chấm điểm vẫn báo H3 > 0. Buổi không có phòng bị phạt ở H3.
- Fitness: `W_hard · Σ vi phạm cứng + Σ wᵢ · vi phạm mềmᵢ`.
- Đánh giá delta (`solver/src/solver/localsearch.py`, lớp `Workspace`): mảng đếm theo ô cho lớp, giảng viên,
  nhóm phòng; dời một buổi chỉ cập nhật ≤ 5 ô. Thiếu phòng ước lượng bằng **điều kiện Hall** trên các nhóm
  phòng lồng nhau (nhóm = tập phòng đủ chỗ cho lớp-môn). Chi phí delta chỉ để định hướng; fitness thật
  luôn tính lại bằng `evaluate()`.
- Tìm kiếm cục bộ (memetic, bật mặc định): **min-conflicts** (chọn ngẫu nhiên buổi đang xung đột, dời tới vị trí
  rẻ nhất hoặc đổi giảng viên) rồi cải thiện mềm `ls_steps` bước.
- Toán tử (`solver/src/solver/ga.py`): tournament k = 3; lai ghép **theo khối lớp** (mỗi lớp lấy nguyên lịch +
  giảng viên từ một bố/mẹ) với xác suất 0,8; đột biến 1–3 thao tác (dời buổi / đổi chỗ hai buổi cùng lớp cùng
  độ dài / đổi giảng viên); thay thế theo thế hệ, giữ 2 cá thể tốt nhất (elitism).
- Khởi tạo: 1 cá thể từ DSatur, còn lại ngẫu nhiên rồi sửa bằng min-conflicts (đa dạng hơn, vẫn hợp lệ).
- Mặc định: quần thể 30, 200 thế hệ, dừng nếu 60 thế hệ không cải thiện.
- Kết quả M4 (100 thế hệ, 3 seed, phạt mềm trung bình ± độ lệch; mọi lịch GA đều 0 vi phạm cứng):

  | Bộ | DSatur | GA memetic | Giảm | Thời gian GA | GA thuần (không tìm kiếm cục bộ, seed 0) |
  |---|---|---|---|---|---|
  | small | 218 ± 6 | **137 ± 3** | 37% | 43 s | 14 vi phạm cứng, mềm 345 |
  | medium | 724 ± 12 | **490 ± 7** | 32% | 48 s | 113 vi phạm cứng, mềm 1 791 |
  | large | 1 271 ± 16 | **994 ± 9** | 22% | 65 s | 394 vi phạm cứng, mềm 3 188 |

  GA thuần không về được lịch hợp lệ sau 100 thế hệ: tìm kiếm cục bộ là thành phần bắt buộc.
  Câu hỏi còn mở cho M6: phần lai ghép đóng góp bao nhiêu so với chỉ chạy tìm kiếm cục bộ nhiều lần
  cùng thời gian (ablation).
- Baseline so sánh: greedy DSatur (`solver/src/solver/dsatur.py`): chọn buổi còn ít lựa chọn hợp lệ nhất
  (tính cả phòng), gán giá trị có chi phí mềm ước lượng thấp nhất + **bám mép** (least-constraining value:
  buổi chạm mép ca hoặc buổi đã xếp, tránh để lại khoảng lẻ). Kết quả 10 seed:

  | Bộ | Lịch hợp lệ | Phạt mềm (TB ± độ lệch) | Tốt nhất | Thời gian |
  |---|---|---|---|---|
  | small | 10/10 | 227 ± 24 | 187 | 0,1 s |
  | medium | 10/10 | 725 ± 12 | 705 | 1,5 s |
  | large | 10/10 | 1 303 ± 40 | 1 257 | 7,9 s |

  GA phải cho phạt mềm thấp hơn các con số này (vi phạm cứng đã về 0 ngay từ baseline).
- Tiền kiểm tra khả thi trước khi chạy (cận dưới về phòng, lớp, giảng viên).

**Giai đoạn 2: trải ra lịch thật**

Cài đặt ở `solver/src/solver/calendar.py`, mất vài ms cho bộ `large`.

- Duyệt từ ngày bắt đầu học kỳ, sinh buổi học có ngày cụ thể từ tuần mẫu cho tới khi đủ số buổi;
  buổi cuối dài phần tiết còn lại.
- Buổi rơi vào ngày lễ: bỏ qua, pattern chạy tiếp sang tuần sau ("lùi"), không cần tìm chỗ mới.
- Hết tuần học mà vẫn thiếu buổi: tìm chỗ **học bù** (ngày sớm nhất, ưu tiên cùng tiết và cùng phòng như tuần mẫu;
  lớp, giảng viên, phòng rảnh; không vào giờ bận; lớp-môn chưa có buổi ngày đó). Lớp-môn ít chỗ bù nhất xếp trước.
  Tham lam, **không quay lui** (khác kế hoạch ban đầu): chỉ những môn kín đủ 15 tuần mới có thể cần bù.
- Vẫn thiếu sau khi bù: vi phạm H9.
- Với bảng quy đổi mặc định, môn dài nhất (2 TC) chỉ học 10 tuần, nên luôn còn ≥ 5 tuần đệm: ngày lễ chỉ làm
  lịch lùi lại, chưa bao giờ cần học bù. Ngày 20/11 trong dữ liệu mẫu rơi vào tuần 11, khi mọi môn đã học xong
  (kết thúc muộn nhất 14/11), nên không ảnh hưởng. Học bù và H9 được kiểm chứng bằng test với môn kín 15 tuần.

**Thực nghiệm:** nhiều seed (trung bình ± độ lệch), đường hội tụ, so với DSatur, ablation (memetic, đánh giá delta).

## 7. Dữ liệu

- Khoa CNTT, **12 ngành**, mỗi ngành 5–8 lớp → khoảng **80 lớp**, mỗi lớp 25–40 sinh viên.
- Chương trình 6 kỳ đào tạo, mỗi kỳ 5–6 môn (15–18 TC). Không có môn tiên quyết, không phân biệt môn chuyên ngành.
- Môn chung (Tiếng Anh, Chính trị...) dùng chung giữa các ngành, do bộ môn riêng dạy.
- Môn **không** tách tín chỉ lý thuyết/thực hành: mỗi môn có một tổng TC và một loại phòng (THEORY / LAB / STUDIO).
- Giảng viên dạy 2–5 môn trong cùng bộ môn.
- **Sinh viên thật** (chốt 2026-11-16, cài ở M8): bảng `students` (thuộc một lớp) và `extra_enrollments`
  (học thêm lớp-môn của lớp khác). **Sĩ số lớp đếm từ bảng sinh viên**, bỏ cột `student_classes.size`.
  Dữ liệu mẫu: **5%** sinh viên (từ kỳ 2 trở lên) học lại 1–2 môn kỳ dưới theo chương trình ngành mình, ở một lớp
  bất kỳ đang học môn đó trong học kỳ (kể cả lớp ngành khác nếu là môn chung).
- Snapshot **không** chứa từng sinh viên: Go gom thành nhóm sinh viên (tập lớp-môn + số sinh viên) và tính sẵn
  sĩ số từng lớp-môn. Đổi định dạng nên `schema_version` lên **2.0** (solver cũ không được âm thầm bỏ qua H10).
- 3 bộ dữ liệu: `small` (11 lớp), `medium` (40 lớp), `large` (76 lớp).
  Bộ sinh dữ liệu tự cân số phòng/giảng viên: tải phòng ≤ 75%, giảng viên trung bình ~16 tiết/tuần.
  Bộ `large` cần ~148 giảng viên (không phải ~80 như ước lượng ban đầu) vì Cách A dồn lịch về đầu kỳ.
  Chi tiết: [tools/datagen/README.md](../tools/datagen/README.md).

## 8. Kiến trúc

- **Go** (`admin/`): CRUD danh mục (gồm sinh viên, học thêm), cấu hình học kỳ, tạo job, xem lịch. Không phân quyền,
  **không xuất file**. Công nghệ đã chốt (2026-11-16):
  - **Giao diện:** render phía server bằng `html/template` + **htmx** (extension SSE cho tiến độ GA). Không SPA, không Node.
    CSS bằng **Tailwind** (standalone CLI, không cần Node); biểu đồ hội tụ bằng **Chart.js**. htmx và Chart.js nhúng vào
    binary (`go:embed`), không dùng CDN.
  - **Tiến độ:** handler SSE đọc `run_progress` mỗi giây (theo `generation` lớn nhất đã gửi); không dùng LISTEN/NOTIFY.
  - **Xem lịch** (mốc cuối, quan trọng nhất): theo một run, chọn tuần mẫu hoặc tuần 1–15.
    1. Thời khoá biểu một đối tượng (lưới Thứ 2–7 × tiết 1–12): theo lớp, sinh viên, giảng viên, phòng, môn.
    2. Bảng tổng: mỗi hàng một đối tượng, cột 6 ngày × 12 tiết, tô màu theo môn, ô trùng tô đỏ.
    3. So sánh 2–4 đối tượng: đặt cạnh nhau hoặc chồng lên (tô đỏ tiết trùng, hiện tiết cùng rảnh).
    4. Kiểm tra trùng lịch bằng SQL trên dữ liệu thật, độc lập với GA: lớp, sinh viên, giảng viên, phòng.
  - **Test:** database riêng `timetable_gotest` (Python dùng `timetable_test`).
  - **Truy cập DB:** **sqlc + pgx/v5**, không dùng ORM. Viết SQL trong `admin/internal/db/queries/*.sql`,
    `sqlc generate` sinh code Go có kiểu từ chính `db/migrations/` (migration là nguồn sự thật duy nhất của schema).
    sqlc chạy qua Docker như golang-migrate, không cài vào máy. Code sinh ra không sửa tay.
    Struct `Queries` do sqlc sinh đóng vai trò repository; service chỉ phụ thuộc interface nhỏ khai báo tại nơi dùng.
  - **Cấu trúc:** chia package theo tính năng trong `admin/internal/` (handler → service → store), nối phụ thuộc tay trong `cmd/admin/main.go`.
- **Python** (`solver/`): worker GA, chỉ đọc `input_snapshot`, không truy vấn bảng danh mục, không migrate.
- **Hợp đồng** (`contracts/`): JSON Schema của `input_snapshot` (v1.0, lên v2.0 ở M8) + `validate.py` kiểm tra chéo,
  và `run_params.schema.json`. Go tính sẵn giá trị suy ra từ tín chỉ; Python không tính lại.
  **Không** có `result.schema.json`: worker ghi thẳng vào DB, Go đọc thẳng từ DB.
- **PostgreSQL**: vừa là DB vừa là hàng đợi (`SELECT … FOR UPDATE SKIP LOCKED`, `heartbeat_at` cho worker chết).
  Không cần Redis/RabbitMQ. Vòng đời một run (`solver/src/solver/worker.py`):
  - `PENDING → RUNNING`: worker nhận job bằng một câu `UPDATE … WHERE id = (SELECT … FOR UPDATE SKIP LOCKED LIMIT 1)`,
    ghi `worker_id`, `started_at`, `heartbeat_at`. Nhiều worker song song không lấy trùng job.
  - Heartbeat: luồng riêng (kết nối riêng) cập nhật `heartbeat_at` mỗi 10 s. Lần cập nhật nào không còn thấy
    `RUNNING` của mình thì báo GA dừng ở thế hệ kế tiếp (hook `should_stop`).
  - `RUNNING → DONE`: ghi `section_assignments`, `template_sessions`, `calendar_sessions` (COPY), `run_violations`
    và cập nhật `schedule_runs` trong **một** transaction. Worker không đụng tới `published_run_id`.
  - `RUNNING → CANCELLED`: admin đổi status; worker dừng, ghi `finished_at`, không ghi kết quả.
  - `RUNNING → FAILED`: snapshot / params lỗi, exception, worker bị tắt (SIGTERM / Ctrl+C), hoặc **job mồ côi**
    (heartbeat quá 60 s, worker nào cũng dọn ở mỗi vòng lặp). Job mồ côi **không** tự chạy lại: một job làm worker
    crash sẽ không lặp vô hạn; admin tạo run mới nếu muốn (nên không cần cột `attempts`).
  - Mọi UPDATE trạng thái đều kèm `status = 'RUNNING' AND worker_id = <mình>`, nên worker không ghi đè job đã bị huỷ
    hoặc bị đánh FAILED; transaction ghi kết quả bị rollback trong trường hợp đó.
  - `params` của run theo `contracts/run_params.schema.json`; thiếu thì lấy mặc định, key lạ thì FAILED.
  - Đo trên bộ `large`, 150 thế hệ: 92 s, 0 vi phạm cứng, ghi 5 805 buổi lịch thật; kiểm tra chéo bằng SQL
    không có trùng phòng / trùng giảng viên, mọi lớp-môn đủ 15 × TC tiết.
- Một học kỳ có nhiều run; `semesters.published_run_id` trỏ tới lịch được công bố.
- Tiến độ GA ghi vào `run_progress`, Go đẩy lên giao diện bằng SSE.
- Schema: `db/migrations/` (golang-migrate, SQL thuần). ERD: 23 bảng (11 + 4 + 6 + 2), chia 4 nhóm:
  danh mục, đầu vào học kỳ, job, kết quả.
  - `000001_master_data`: danh mục; seed sẵn `room_types` và bảng quy đổi `credit_rules` mặc định.
  - `000002_semester_input`: học kỳ, ngày lễ, lớp trong học kỳ, lớp-môn.
  - `000003_runs_and_results`: job, tiến độ, phân công, tuần mẫu, lịch thật, vi phạm.
  - `000004_students`: `students`, `extra_enrollments` (chỉ lưu phần học thêm); bỏ `student_classes.size`.
    "Không học thêm lớp-môn của chính lớp mình" kiểm tra ở tầng ứng dụng và `validate.py` (CHECK không so được hai bảng).
  - Ràng buộc nào kiểm tra được trên một dòng thì đặt CHECK ở DB (H8, quy tắc quy đổi TC, ngày học không phải Chủ nhật).
    Ràng buộc chồng giờ (H1–H3) **không** đặt ở DB, vì lịch còn vi phạm vẫn phải lưu được.
