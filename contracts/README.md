# Hợp đồng Go ↔ Python

`input_snapshot` là ranh giới **duy nhất** giữa web quản trị (Go) và solver (Python).
Khi tạo job, Go đóng băng toàn bộ đầu vào vào `schedule_runs.input_snapshot`;
Python chỉ đọc snapshot, không truy vấn các bảng danh mục.

| File | Nội dung |
|---|---|
| `input_snapshot.schema.json` | JSON Schema (draft 2020-12): cấu trúc, kiểu, miền giá trị |
| `validate.py` | Kiểm tra schema + ràng buộc chéo mà JSON Schema không diễn đạt được |
| `examples/input_snapshot.tiny.json` | Ví dụ nhỏ: 2 lớp, 3 môn, 6 lớp-môn |
| `run_params.schema.json` | JSON Schema của `schedule_runs.params` (tham số GA + trọng số ràng buộc mềm) |

```bash
python3 contracts/validate.py contracts/examples/input_snapshot.tiny.json
```

## Phân vai

**Go chịu trách nhiệm:**
- Chỉ đưa vào snapshot những gì liên quan tới học kỳ: lớp trong `semester_classes`,
  môn có lớp-môn, giảng viên dạy được ít nhất một môn đó, toàn bộ phòng.
- Tính sẵn các giá trị suy ra cho mỗi lớp-môn từ `credit_rules`:
  `total_periods = 15 × TC`, `periods_per_session`, `sessions_per_week`,
  `total_sessions = ceil(total_periods / periods_per_session)`.
  Logic quy đổi chỉ nằm ở một chỗ (Go), Python không tính lại.
- Gộp `lecturer_slots` thành hai danh sách `unavailable` / `preferred` của từng giảng viên.
- Chạy kiểm tra tương đương `validate.py` trước khi tạo job.

**Python chịu trách nhiệm:**
- Từ chối snapshot có `schema_version` không hỗ trợ.
- Chạy `validate.py` khi nạp; lỗi thì đánh dấu run `FAILED` kèm danh sách lỗi.
- Không dựa vào thứ tự phần tử trong mảng, chỉ dựa vào `id`.

## Những gì `validate.py` kiểm tra thêm ngoài schema

- Học kỳ bắt đầu Thứ 2, đủ số tuần, ngày lễ nằm trong học kỳ.
- Các ca không chồng nhau.
- `id` và `code` không trùng; mọi `class_id`, `subject_id` tham chiếu tồn tại.
- Một lớp không học một môn hai lần.
- Giá trị suy ra của lớp-môn khớp số tín chỉ; buổi cuối ≥ 2 tiết; môn ≥ 4 TC có buổi ≥ 3 tiết;
  buổi không dài hơn ca; học xong trong số tuần học (H9).
- Mỗi lớp-môn có ít nhất một giảng viên dạy được và một phòng đúng loại đủ sức chứa.
  Thiếu thì bài toán chắc chắn vô nghiệm, không cần chạy GA.

## Đổi phiên bản

Thêm trường tuỳ chọn mà Python cũ bỏ qua được: giữ `schema_version`.
Đổi tên, xoá, đổi nghĩa trường: tăng `schema_version`, cập nhật cả Go và Python trong cùng một lần đổi.
