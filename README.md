# GA Timetable

Xếp thời khoá biểu học kỳ cho trường cao đẳng bằng giải thuật di truyền (GA).

- `admin/`: web quản trị (Go): quản lý dữ liệu, tạo job xếp lịch, xem kết quả
- `solver/`: worker GA (Python): lấy job từ PostgreSQL, xếp lịch, ghi kết quả
- `db/migrations/`: schema (SQL thuần, chạy bằng golang-migrate)
- `contracts/`: JSON schema của `input_snapshot`, hợp đồng giữa Go và Python
- `docs/`: đặc tả bài toán và các quyết định thiết kế
- `tools/datagen/`: sinh dữ liệu mẫu (small / medium / large) vào `db/seeds/`

Đặc tả đầy đủ: [docs/decisions.md](docs/decisions.md)

## Chạy database

```bash
cp .env.example .env
docker compose up -d db
docker compose run --rm migrate up
docker compose exec -T db psql -U timetable -d timetable -v ON_ERROR_STOP=1 < db/seeds/large.sql
```
