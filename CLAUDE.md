# CLAUDE.md

Bàn giao ngữ cảnh cho mọi phiên Claude Code làm việc trên repo này.
Đặc tả bài toán đầy đủ nằm ở [docs/decisions.md](docs/decisions.md): đọc file đó trước khi đổi bất cứ gì về bài toán.

## Bối cảnh

- Chủ repo trước đây làm chức năng xếp thời khoá biểu bằng giải thuật di truyền (GA) ở một trường cao đẳng.
  Bản cũ "làm không chuẩn GA lắm". Repo này **làm lại cho đúng, ở quy mô nhỏ, để đưa vào CV**.
- Trọng tâm là **giải thuật** (GA memetic, cấu trúc dữ liệu, hiệu năng). Dữ liệu chỉ cần hợp lý, không cần chi tiết
  (không có môn tiên quyết, không có ngữ nghĩa riêng của từng ngành).
- Bài toán có **sinh viên thật** (chốt 2026-11-16): sinh viên học toàn bộ lớp-môn của lớp mình, cộng lớp-môn học thêm
  ở lớp khác; ràng buộc cứng H10 chống trùng lịch theo sinh viên.
- Kiến trúc: **Python** (`solver/`) chạy GA; **Go** (`admin/`) làm web quản trị (chưa làm);
  **PostgreSQL** vừa là DB vừa là hàng đợi job. Ranh giới Go ↔ Python là `input_snapshot`
  (xem [contracts/README.md](contracts/README.md)).

## Cách làm việc với chủ repo

- Trao đổi bằng **tiếng Việt**.
- Làm **từng bước**. Trước mỗi mốc, giải thích kế hoạch (làm gì, vì sao, cần chốt gì), rồi **chờ duyệt**.
  Chủ repo thường hỏi "Bước Mx làm những gì", sau đó mới nói "Làm Mx".
- Những gì không giúp ích cho code hoặc cho bài toán thì hoãn lại (ví dụ M6).
- Hỏi trước khi cài phần mềm hoặc thêm thư viện (máy chưa có Go).
- Chủ repo xem DB bằng **Navicat** (`localhost:5432`, user/pass/db đều là `timetable`).
  Sau khi chạy gì ghi vào DB thì nói rõ nên xem bảng nào.
- Chủ repo **chưa code Go bao giờ**, quen PHP/Laravel (repository pattern...). Khi làm `admin/`, giải thích kỹ hơn
  bình thường và đối chiếu với khái niệm tương đương trong Laravel.
- **Git:** repo cá nhân `git@github.com:yukihirakirito/ga_timetable.git`. Chỉ commit/push khi được yêu cầu.
  Phải dùng tài khoản cá nhân (`yukihirakirito`), **không bao giờ** dùng tài khoản công ty `mor-dont`.
  Mỗi máy cần đặt riêng cho repo này `user.name`/`user.email` cá nhân và `core.sshCommand` trỏ tới SSH key cá nhân.

## Trạng thái (cập nhật 2026-11-16)

| Mốc | Nội dung | Trạng thái |
|---|---|---|
| Thiết kế | Đặc tả, ERD 21 bảng, DDL (3 migration), JSON contract, bộ sinh dữ liệu small/medium/large | ✅ |
| M1 | `problem.py`: nạp snapshot, tính sẵn miền giá trị (H7, H8) | ✅ |
| M2 | `evaluate.py` + `rooms.py`: chấm H1–H6, S1–S8, gán phòng khi decode | ✅ |
| M3 | `dsatur.py`: baseline tham lam | ✅ |
| M4 | `ga.py` + `localsearch.py`: GA memetic, đánh giá delta | ✅ |
| M5 | `calendar.py`: trải tuần mẫu ra ngày thật, ngày lễ, học bù, H9 | ✅ |
| M6 | Thực nghiệm: so sánh với tìm kiếm cục bộ lặp nhiều lần trong cùng thời gian, ablation, đường hội tụ, biểu đồ | ⏸ **Hoãn** theo quyết định của chủ repo |
| M7 | `worker.py` + `params.py`: hàng đợi Postgres (SKIP LOCKED), heartbeat, huỷ, job mồ côi → FAILED, ghi kết quả trong 1 transaction | ✅ |
| M8a | Sinh viên thật: đặc tả H10, migration `000004` (`students`, `extra_enrollments`, bỏ `student_classes.size`), bộ sinh dữ liệu (5% SV học lại), snapshot **2.0** (`sections[].size`, `student_groups`) + `validate.py`, `problem.py` nạp nhóm (`group_class`, `group_extra`, `group_students`) | ✅ |
| **M8b** | Solver hỗ trợ nhóm sinh viên: một buổi thuộc nhiều nhóm; H10 trong `evaluate` + `violations()`, delta `Workspace`, DSatur, học bù (`calendar`), lai ghép theo khối lớp. Đo lại `large` | ⏳ **Tiếp theo**. ⚠️ Trước khi xong M8b, solver nạp nhóm nhưng **chưa phạt H10**: lịch có thể trùng giờ với SV học lại |
| G1 | Go: khung project (go.mod, main.go, config, pgxpool, sqlc, layout + htmx + Tailwind, middleware, test với `timetable_gotest`) | ⏳ |
| G2 | Go: tạo snapshot 2.0 từ DB + kiểm tra (JSON Schema + kiểm tra ngữ nghĩa như `validate.py`). Xong khi khớp `db/seeds/large.snapshot.json` | ⏳ |
| G3 | Go: tạo run (params theo `run_params.schema.json`), trang tiến độ SSE + Chart.js, huỷ run | ⏳ |
| G4 | Go: CRUD danh mục, gồm sinh viên và học thêm; đổi lỗi DB thành thông báo dễ hiểu | ⏳ |
| G5 | Go: cấu hình học kỳ (ngày lễ, lớp + `term_no`), sinh lớp-môn từ chương trình đào tạo, cảnh báo thiếu GV/phòng | ⏳ |
| G6 | Go: **xem lịch** (mốc cuối, quan trọng nhất): 4 màn hình + kiểm tra trùng lịch lớp/SV/GV/phòng, công bố run. Xem [docs/decisions.md](docs/decisions.md) §8 | ⏳ |
| G7 | Đóng gói (tuỳ chọn): Dockerfile, compose cả hệ thống, GitHub Actions, README có ảnh | ⏳ |

Test: **100 passed** (`cd solver && uv run pytest`). Trong đó 11 test worker cần Postgres, không có thì tự skip.

Kết quả đã đo (phạt mềm, càng nhỏ càng tốt; mọi lịch GA đều 0 vi phạm cứng):

| Bộ | DSatur (10 seed) | GA 100 thế hệ (3 seed) |
|---|---|---|
| small | 227 ± 24 | 137 ± 3 (−37%) |
| medium | 725 ± 12 | 490 ± 7 (−32%) |
| large | 1303 ± 40 | 994 ± 9 (−22%) |

Worker trên `large`, 150 thế hệ: 92 s, 0 vi phạm cứng, 5 805 buổi lịch thật. GA không có tìm kiếm cục bộ thì thất bại
(394 vi phạm cứng trên `large`).

Việc còn để ngỏ:
- Công nghệ Go đã chốt (chi tiết [docs/decisions.md](docs/decisions.md) §8): `html/template` + htmx, Tailwind
  (standalone CLI, cần hỏi trước khi tải), Chart.js, sqlc + pgx/v5, santhosh-tekuri/jsonschema/v6, SSE đọc
  `run_progress` mỗi giây. **Không** xuất file lịch, **không** có `result.schema.json`.
- Câu hỏi cho M6: GA có hơn tìm kiếm cục bộ lặp nhiều lần trong cùng ngân sách thời gian không?
- Đã bỏ hẳn (2026-11-16, chủ repo quyết định), không đề xuất lại: lịch thi, chia kỳ làm 2 nửa (Cách B),
  cho GA chọn độ dài buổi, benchmark ITC-2007.

## Dựng môi trường trên máy mới

```bash
cp .env.example .env
docker compose up -d db
docker compose run --rm migrate up
docker compose exec -T db psql -U timetable -d timetable -v ON_ERROR_STOP=1 < db/seeds/large.sql
cd solver && uv sync && uv run pytest
```

Cần Docker, [uv](https://docs.astral.sh/uv/) và Go. Trên máy cũ, uv nằm ở `~/.local/bin/uv` và có thể không có
trong PATH của phiên Claude; khi đó gọi bằng đường dẫn đầy đủ.

Cài Go (không cần sudo): tải bản linux-amd64 mới nhất từ https://go.dev/dl/, kiểm tra sha256, giải nén vào `~/.local`
(được `~/.local/go`), thêm `$HOME/.local/go/bin` và `$HOME/go/bin` vào PATH. Máy cũ đang dùng go1.27.4.
VSCode cần extension "Go" (Go Team at Google), extension sẽ đề nghị cài `gopls`.
sqlc không cài vào máy: chạy qua Docker bằng `docker compose run --rm sqlc generate` (image `sqlc/sqlc:1.31.1`).

## Lệnh thường dùng (trong `solver/`)

```bash
uv run solver info ../db/seeds/large.snapshot.json
uv run solver dsatur ../db/seeds/large.snapshot.json --seeds 10
uv run solver ga ../db/seeds/large.snapshot.json --generations 100 --out ga.json
uv run solver calendar ../db/seeds/large.snapshot.json --schedule ga.json --show-class SE-K2-01 --week 3
uv run solver enqueue ../db/seeds/large.snapshot.json --params '{"ga":{"generations":150}}'
uv run solver worker --once
```

Sinh lại dữ liệu mẫu: `python3 tools/datagen/generate.py [small|medium|large]` (Python hệ thống, cần `pyyaml`;
`uv run` trong `solver/` không có `yaml`).

## Quy ước và những chỗ dễ sai

- **Fitness chỉ có điểm phạt:** `10 000 × Σ vi phạm cứng + Σ wᵢ × vi phạm mềmᵢ`, càng nhỏ càng tốt.
  Trọng số do chủ repo chốt: hard 10 000, S2 = 5, S8 = 5. Phạt mềm của một lịch phải luôn nhỏ hơn 10 000
  (lịch tốt hiện khoảng 1 000–1 300).
- **S3 đã bị bỏ, nhưng không đánh số lại** các mã còn lại: S1, S2, S4…S8.
- **Ô thời gian:** `cell = day * 12 + period`, đếm từ 0 (day 0 = Thứ 2). Trong DB thì `day` và `start_period` đếm từ 1.
- **Python không tự tính lại** giá trị suy ra từ tín chỉ (`total_periods`, `total_sessions`…): Go tính sẵn và đưa vào snapshot.
- Vector `Workspace` (delta) chỉ dùng để dẫn hướng tìm kiếm cục bộ; fitness thật luôn lấy từ `evaluate()`.
- Lịch còn vi phạm vẫn phải lưu được, nên DB **không** có ràng buộc chống chồng giờ (H1–H3).
- **Không dùng `TRUNCATE schedule_runs CASCADE`:** `semesters.published_run_id` có khoá ngoại trỏ tới `schedule_runs`,
  nên CASCADE sẽ xoá luôn học kỳ và lớp-môn. Muốn xoá các run thì dùng `DELETE FROM schedule_runs`.
- Test worker dùng database riêng `timetable_test` (tạo lại mỗi lần chạy) để không đụng vào DB `timetable` đang xem trong Navicat.
- `db/seeds/*` do `tools/datagen/generate.py` sinh ra, chạy lại luôn ra cùng kết quả: **không sửa tay**.
  Id trong `*.snapshot.json` trùng với id trong DB.
- Với bảng quy đổi mặc định, môn dài nhất chỉ học 10 tuần, nên ngày lễ 20/11 (tuần 11) không ảnh hưởng dữ liệu mẫu,
  và học bù chưa từng xảy ra trên dữ liệu mẫu. Học bù và H9 chỉ được kiểm chứng bằng test; muốn thử thì dùng `--holiday`.
- Mọi thay đổi về bài toán: sửa [docs/decisions.md](docs/decisions.md) trước rồi mới sửa code.
