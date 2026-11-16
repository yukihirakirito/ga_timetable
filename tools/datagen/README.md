# Sinh dữ liệu mẫu

```bash
python3 tools/datagen/generate.py            # sinh cả 3 bộ
python3 tools/datagen/generate.py medium     # chỉ một bộ
```

| File | Vai trò |
|---|---|
| `curriculum.yaml` | Viết tay: bộ môn, 12 ngành, môn học, chương trình 6 kỳ |
| `generate.py` | Sinh lớp, lớp-môn, giảng viên, phòng, sinh viên (có seed, chạy lại ra y hệt). Cần Python có `pyyaml` (chạy bằng `python3` của hệ thống, không phải `uv run` trong `solver/`) |
| `db/seeds/<bộ>.sql` | Nạp vào PostgreSQL; **xoá dữ liệu cũ** (trừ `room_types`, `credit_rules`) |
| `db/seeds/<bộ>.snapshot.json` | `input_snapshot` tương ứng, dùng phát triển solver trước khi có Go |

Nạp một bộ vào database:

```bash
docker compose exec -T db psql -U timetable -d timetable -v ON_ERROR_STOP=1 < db/seeds/large.sql
```

## Chương trình đào tạo

Mỗi ngành, mỗi kỳ = **môn chung** (mọi ngành) + **môn nhóm ngành** + **môn riêng của ngành**.
Mỗi kỳ 5–6 môn, 15–17 tín chỉ; script tự kiểm tra tổng tín chỉ nằm trong 15–18.

| Nhóm | Ngành | Bộ môn của môn nhóm |
|---|---|---|
| SOFT | SE, WEB, MOB, QA | Công nghệ phần mềm |
| DATA | AI, DA | Dữ liệu và AI |
| INFRA | SEC, NET, CLD, IOT | Hạ tầng và An ninh mạng |
| DESIGN | UX, GAME | Thiết kế |

Môn chung (Tiếng Anh 1–4, các môn chính trị, pháp luật, kỹ năng) do bộ môn Ngoại ngữ /
Lý luận chính trị dạy. Dùng chung nhiều môn giữa các ngành có chủ đích: một môn có nhiều lớp-môn
và nhiều giảng viên dạy được, nên GA thực sự phải chọn giảng viên.

## Quy tắc sinh

- **Lớp:** mỗi ngành 5–8 lớp, kỳ 1 luôn có lớp, dư thì dồn về kỳ đầu; sĩ số 25–40.
  Mã lớp `SE-K3-01` = ngành SE, kỳ đào tạo 3, lớp số 1.
- **Lớp-môn:** lớp học toàn bộ môn của (ngành, kỳ đào tạo).
- **Giảng viên:** sinh theo bộ môn, số người = max(nhu cầu / 16 tiết, đủ để mỗi môn có ≥ 2 người,
  mỗi người ≤ 5 môn). Môn nhiều tiết có nhiều người dạy được hơn. Mỗi người dạy 2–5 môn trong bộ môn,
  tối đa 16/20/24 tiết/tuần; ~30% bận 1–2 nửa ngày, ~25% có 1–2 nửa ngày ưu tiên.
- **Sinh viên:** mỗi lớp đúng số sinh viên của lớp (25–40), mã `SV00001…`. **5% tổng số sinh viên** (chỉ từ kỳ 2
  trở lên) học lại 1–2 môn của kỳ dưới theo chương trình ngành mình, ở một lớp bất kỳ đang học môn đó (kể cả lớp
  ngành khác nếu là môn chung). Dùng bộ số ngẫu nhiên riêng, nên thêm sinh viên không làm đổi lớp, lớp-môn, giảng viên.
- **Phòng:** theo loại, đủ để tải ≤ 75%; thêm phòng lớn nếu lớp-môn đông không đủ chỗ (sĩ số lớp-môn tính cả sinh
  viên học thêm; vượt cả phòng lớn nhất thì thêm phòng đúng cỡ).
- **Học kỳ:** Fall 2026, 07/09/2026 – 09/01/2027. Ngày lễ: 20/11 (tuần học 11, để thử học bù)
  và 01/01 (rơi vào tuần thi).

## Kết quả hiện tại

| Bộ | Ngành | Lớp | Lớp-môn | Môn có lớp | Giảng viên | Phòng (LT / Lab / Studio) | Tải phòng | Tải GV |
|---|---|---|---|---|---|---|---|---|
| small | 2 | 11 | 64 | 41 | 23 | 3 / 5 / – | 58% / 59% | 75% |
| medium | 6 | 40 | 234 | 97 | 81 | 9 / 13 / 3 | 75% / 71% / 39% | 76% |
| large | 12 | 76 | 444 | 154 | 148 | 18 / 24 / 3 | 74% / 74% / 52% | 80% |

| Bộ | Sinh viên | Học lại | Lượt học thêm | Nhóm (snapshot) | Lớp-môn có SV học thêm | Sĩ số lớp-môn tối đa |
|---|---|---|---|---|---|---|
| small | 392 | 20 (5,1%) | 30 | 19 | 20 | 42 |
| medium | 1 357 | 68 (5,0%) | 105 | 68 | 82 | 42 |
| large | 2 477 | 124 (5,0%) | 187 | 124 | 133 | 42 |

Bộ `small` thêm 1 phòng LAB so với khi chưa có sinh viên (7 → 8 phòng); `medium`, `large` không đổi.

Tải GV = tổng tiết/tuần cần dạy ÷ tổng số tiết tối đa của mọi giảng viên.
Mỗi lớp học 28–33 tiết/tuần trên sức chứa 72.

Số giảng viên cao hơn ước lượng ban đầu (~80) vì Cách A dồn lịch về đầu kỳ: môn 3–5 TC học
2 buổi/tuần, tổng nhu cầu bộ `large` là ~2350 tiết/tuần trong tuần mẫu.
