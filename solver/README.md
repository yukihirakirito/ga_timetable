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
| `cli.py` | Lệnh `solver` |

## Quy ước

- **Ô thời gian:** `cell = day * 12 + period` (0-based, day 0 = Thứ 2, period 0 = tiết 1).
  Buổi dài L bắt đầu ở `start` chiếm các ô `start .. start + L - 1`.
- **Fitness** = `10 000 × Σ vi phạm cứng + Σ wᵢ × vi phạm mềmᵢ`, chỉ có điểm phạt, càng nhỏ càng tốt.
  Trọng số mặc định ở `evaluate.Weights`; sau này lấy từ `params` của run.
