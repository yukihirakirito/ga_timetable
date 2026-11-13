# Solver (Python)

Cần [uv](https://docs.astral.sh/uv/) (cài ở `~/.local/bin/uv`).

```bash
cd solver
uv sync                                                  # cài môi trường (.venv)
uv run pytest                                            # chạy test
uv run solver info ../db/seeds/large.snapshot.json       # thống kê bài toán
uv run solver evaluate ../db/seeds/large.snapshot.json   # chấm một lời giải ngẫu nhiên
uv run solver dsatur ../db/seeds/large.snapshot.json --seeds 10   # baseline DSatur
uv run solver ga ../db/seeds/large.snapshot.json --generations 100 --out ga.json   # GA memetic + lịch thật
# Trải lịch đã lưu ra lịch thật, thử thêm ngày lễ, in thời khoá biểu một lớp
uv run solver calendar ../db/seeds/large.snapshot.json --schedule ga.json \
    --holiday 2026-09-21 --show-class SE-K2-01 --week 3
```

### Chạy như worker (cần DB: xem README gốc)

Web Go chỉ cần INSERT một dòng `PENDING` vào `schedule_runs`. Khi chưa có Go, dùng `enqueue` để tạo job:

```bash
uv run solver enqueue ../db/seeds/large.snapshot.json --params '{"ga":{"generations":150,"time_limit":120}}'
uv run solver worker            # chạy liên tục, Ctrl+C để dừng (job đang chạy -> FAILED)
uv run solver worker --once     # xử lý hết hàng đợi rồi thoát
```

- Kết nối: `DATABASE_URL`, hoặc ghép từ `DB_*` trong biến môi trường / file `.env` ở gốc repo.
- `params` của run: xem [contracts/run_params.schema.json](../contracts/run_params.schema.json); thiếu thì lấy mặc định,
  key lạ thì run `FAILED`. `enqueue` lưu params ở dạng đầy đủ (đã điền mặc định).
- Huỷ job đang chạy: `UPDATE schedule_runs SET status = 'CANCELLED' WHERE id = …`; worker dừng GA trong ≤ 1 chu kỳ
  heartbeat (10 s) và không ghi kết quả.
- Chạy nhiều worker song song được: mỗi worker nhận một job khác nhau (`FOR UPDATE SKIP LOCKED`).
- Test tích hợp (`tests/test_worker.py`) dùng database riêng `timetable_test` (tự tạo lại mỗi lần chạy),
  tự bỏ qua khi không kết nối được PostgreSQL.

## Cấu trúc

| Module | Vai trò |
|---|---|
| `problem.py` | Nạp + kiểm tra snapshot, đánh chỉ số lại, tính sẵn miền giá trị (H7, H8) |
| `schedule.py` | Nhiễm sắc thể: `lecturer[lớp-môn]` + `start[buổi]`; sinh ngẫu nhiên; kiểm tra miền |
| `rooms.py` | Gán phòng: tham lam kiểu interval partitioning (khó xếp trước, best-fit, giữ phòng S7) + tìm đường tăng khi kẹt |
| `evaluate.py` | Chấm H1–H6, S1–S8 (vector hoá bằng NumPy); `violations()` xuất chi tiết cho `run_violations` |
| `dsatur.py` | Baseline tham lam DSatur: buổi ít lựa chọn nhất trước, giá trị ít gây hạn chế nhất ("bám mép") |
| `localsearch.py` | `Workspace` cập nhật delta (mảng đếm theo ô); min-conflicts sửa xung đột; cải thiện mềm |
| `ga.py` | GA memetic: tournament, lai ghép theo khối lớp, đột biến 3 loại, elitism, dừng theo thế hệ / thời gian / trì trệ |
| `calendar.py` | Giai đoạn 2: trải tuần mẫu ra ngày thật, lùi buổi trúng ngày lễ, học bù, kiểm tra H9 |
| `params.py` | Đọc `schedule_runs.params` (kiểm tra theo schema) thành `GAParams` + `Weights` |
| `worker.py` | Hàng đợi trên PostgreSQL: nhận job (SKIP LOCKED), heartbeat, huỷ, dọn job mồ côi, ghi kết quả trong một transaction |
| `cli.py` | Lệnh `solver` |

## Quy ước

- **Ô thời gian:** `cell = day * 12 + period` (0-based, day 0 = Thứ 2, period 0 = tiết 1).
  Buổi dài L bắt đầu ở `start` chiếm các ô `start .. start + L - 1`.
- **Fitness** = `10 000 × Σ vi phạm cứng + Σ wᵢ × vi phạm mềmᵢ`, chỉ có điểm phạt, càng nhỏ càng tốt.
  Trọng số mặc định ở `evaluate.Weights`; mỗi run ghi đè được qua `params.weights`.
