"""Gán phòng khi decode, làm riêng cho từng ngày (các loại phòng tách nhau tự nhiên vì tập phòng dùng được rời nhau).

Mỗi buổi học trong một ngày là một khoảng tiết [start, start + len). Chia các khoảng vào phòng sao cho
các khoảng cùng phòng không chồng nhau là bài **tô màu đồ thị khoảng** (interval partitioning).
Khi mọi phòng giống nhau, xếp lần lượt theo giờ bắt đầu và lấy phòng rảnh bất kỳ cho lời giải tối ưu:
số phòng dùng = số buổi chồng nhau nhiều nhất cùng lúc.

Phòng thật khác nhau về sức chứa (mỗi buổi chỉ dùng được các phòng đủ chỗ), nên làm hai bước:

**1. Tham lam.** Xếp theo thứ tự:
   (a) buổi **ít phòng dùng được nhất** trước (lớp đông chỉ vừa vài phòng lớn; cùng ý tưởng DSatur);
   (b) cùng mức thì theo giờ bắt đầu (giữ tính tối ưu của interval partitioning trong từng mức);
   (c) cùng giờ thì lớp đông trước.
   Mỗi buổi giữ lại phòng lớp-môn đã dùng ở ngày trước nếu còn rảnh (S7), nếu không lấy phòng
   **nhỏ nhất vẫn đủ chỗ** (best-fit).

**2. Tìm đường tăng (augmenting path)** khi một buổi không còn phòng rảnh, giống ghép cặp hai phía:
   chọn một phòng dùng được mà chỉ có **đúng một** buổi chồng giờ, tạm gỡ buổi đó, xếp buổi mới vào,
   rồi đệ quy tìm phòng khác cho buổi bị gỡ (sâu tối đa MAX_DEPTH tầng, tối đa MAX_STEPS lần đẩy
   cho mỗi buổi kẹt để không bùng nổ khi lịch có rất nhiều xung đột). Thất bại thì hoàn tác.
   Ví dụ phòng A(40), B(60): x(30 SV, tiết 1-3) lấy A, y(30 SV, tiết 2-6) lấy B, z(50 SV, tiết 4-6)
   kẹt. Đường tăng: z chiếm B, đẩy y sang A? A bận tiết 1-3 do x -> đẩy tiếp x sang B (rảnh tiết 1-3) -> xong.

Phòng rảnh hay không được kiểm tra trên mảng `owner[phòng][tiết]` (buổi đang chiếm, -1 nếu rảnh).
Vẫn là heuristic (độ sâu có giới hạn): có thể trả NO_ROOM dù vẫn tồn tại cách xếp. Buổi không có phòng bị phạt ở H3.
"""

from __future__ import annotations

import numpy as np

from .problem import Problem

NO_ROOM = -1
# Đo trên 3 bộ dữ liệu (5 lịch DSatur mỗi bộ): độ sâu 2 / 5 lần đẩy đã đạt gần hết mức giảm H3
# (large: 16 -> 3 buổi thiếu phòng); tăng lên 3 / 30 không giảm thêm mà chậm gấp ~3,5 lần với lịch ngẫu nhiên.
MAX_DEPTH = 2     # số tầng đẩy tối đa
MAX_STEPS = 5     # số lần đẩy tối đa cho mỗi buổi kẹt (chặn bùng nổ khi lịch có rất nhiều xung đột)


def assign_rooms(problem: Problem, start: np.ndarray) -> np.ndarray:
    """Trả về mảng room[e] (chỉ số phòng, hoặc NO_ROOM) cho mọi buổi học."""
    p = problem
    day = start // p.n_periods
    n_fit = np.array([len(f) for f in p.sec_usable_rooms])[p.ev_section]
    # Ngày tăng dần để ưu tiên S7 lan từ ngày trước sang ngày sau
    order = np.lexsort((-p.ev_size, start, n_fit, day))

    # Vòng lặp chạy trên list Python thuần: truy cập từng phần tử mảng NumPy chậm hơn nhiều
    fits = p.sec_usable_rooms_list
    sec = p.ev_section.tolist()
    first = (start % p.n_periods).tolist()
    length = p.ev_len.tolist()
    day_l = day.tolist()
    room = [NO_ROOM] * p.n_events
    last_room: dict[int, int] = {}

    current_day = -1
    owner: list[list[int]] = []

    def is_free(r: int, e: int) -> bool:
        row = owner[r]
        return all(row[t] == -1 for t in range(first[e], first[e] + length[e]))

    def put(r: int, e: int) -> None:
        row = owner[r]
        for t in range(first[e], first[e] + length[e]):
            row[t] = e
        room[e] = r

    def take(e: int) -> None:
        row = owner[room[e]]
        for t in range(first[e], first[e] + length[e]):
            row[t] = -1
        room[e] = NO_ROOM

    budget = [0]

    def augment(e: int, depth: int, locked: set[int]) -> bool:
        """Xếp e vào một phòng, được phép đẩy buổi khác đi (đệ quy). locked: phòng không được đụng lại."""
        for r in fits[sec[e]]:
            if r not in locked and is_free(r, e):
                put(r, e)
                return True
        if depth == 0:
            return False
        for r in fits[sec[e]]:
            if r in locked or budget[0] <= 0:
                continue
            row = owner[r]
            blockers = {row[t] for t in range(first[e], first[e] + length[e])} - {-1}
            if len(blockers) != 1:   # chỉ đẩy khi đúng một buổi chặn: giữ cây tìm kiếm hẹp
                continue
            budget[0] -= 1
            b = blockers.pop()
            take(b)
            put(r, e)
            if augment(b, depth - 1, locked | {r}):
                return True
            take(e)                  # hoàn tác
            put(r, b)
        return False

    for e in order.tolist():
        if day_l[e] != current_day:
            current_day = day_l[e]
            owner = [[-1] * p.n_periods for _ in range(p.n_rooms)]
        s = sec[e]
        prev = last_room.get(s)
        budget[0] = MAX_STEPS
        if prev is not None and is_free(prev, e):
            put(prev, e)
        elif not augment(e, MAX_DEPTH, set()):
            continue
        last_room[s] = room[e]

    return np.array(room, dtype=np.int64)
