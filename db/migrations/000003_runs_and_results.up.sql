-- Nhóm C + D: job của solver (hàng đợi) và kết quả xếp lịch
BEGIN;

-- Mỗi lần chạy GA cho một học kỳ là một run. Bảng này đồng thời là hàng đợi:
-- worker lấy job bằng SELECT ... WHERE status = 'PENDING' FOR UPDATE SKIP LOCKED.
CREATE TABLE schedule_runs (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    semester_id     integer     NOT NULL REFERENCES semesters (id) ON DELETE CASCADE,
    status          text        NOT NULL DEFAULT 'PENDING'
        CHECK (status IN ('PENDING', 'RUNNING', 'DONE', 'FAILED', 'CANCELLED')),
    params          jsonb       NOT NULL DEFAULT '{}'::jsonb,   -- pop_size, generations, seed, weights...
    input_snapshot  jsonb       NOT NULL,                       -- đầu vào đóng băng, xem contracts/
    worker_id       text,
    heartbeat_at    timestamptz,
    best_fitness    double precision,
    hard_violations integer CHECK (hard_violations >= 0),
    soft_penalty    double precision,
    error           text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    started_at      timestamptz,
    finished_at     timestamptz,
    -- Cho phép semesters tham chiếu (semester_id, id) để run công bố phải cùng học kỳ
    CONSTRAINT schedule_runs_semester_id_uq UNIQUE (semester_id, id),
    CONSTRAINT schedule_runs_started_ck
        CHECK (status = 'PENDING' OR status = 'CANCELLED' OR started_at IS NOT NULL),
    CONSTRAINT schedule_runs_finished_ck
        CHECK (status NOT IN ('DONE', 'FAILED') OR finished_at IS NOT NULL)
);
-- Hàng đợi: chỉ index các job đang chờ
CREATE INDEX schedule_runs_pending_idx ON schedule_runs (created_at) WHERE status = 'PENDING';
-- Phát hiện worker chết: job RUNNING có heartbeat quá hạn
CREATE INDEX schedule_runs_running_idx ON schedule_runs (heartbeat_at) WHERE status = 'RUNNING';

-- Lịch được công bố của học kỳ (phải là run của chính học kỳ đó)
ALTER TABLE semesters
    ADD CONSTRAINT semesters_published_run_fk
    FOREIGN KEY (id, published_run_id)
    REFERENCES schedule_runs (semester_id, id)
    ON DELETE SET NULL (published_run_id);

-- Đường hội tụ: worker ghi mỗi K thế hệ
CREATE TABLE run_progress (
    run_id          bigint  NOT NULL REFERENCES schedule_runs (id) ON DELETE CASCADE,
    generation      integer NOT NULL CHECK (generation >= 0),
    best_fitness    double precision NOT NULL,
    avg_fitness     double precision NOT NULL,
    hard_violations integer NOT NULL CHECK (hard_violations >= 0),
    elapsed_ms      integer NOT NULL CHECK (elapsed_ms >= 0),
    PRIMARY KEY (run_id, generation)
);

-- GA phân công giảng viên cho từng lớp-môn
CREATE TABLE section_assignments (
    run_id      bigint  NOT NULL REFERENCES schedule_runs (id) ON DELETE CASCADE,
    section_id  integer NOT NULL REFERENCES course_sections (id) ON DELETE CASCADE,
    lecturer_id integer NOT NULL REFERENCES lecturers (id),
    PRIMARY KEY (run_id, section_id)
);
CREATE INDEX section_assignments_lecturer_idx ON section_assignments (run_id, lecturer_id);

-- Giai đoạn 1: tuần mẫu.
-- Không dùng EXCLUDE chống trùng phòng/giờ: GA có thể trả về lịch còn vi phạm,
-- lịch đó vẫn phải lưu được để hiển thị, vi phạm ghi ở run_violations.
CREATE TABLE template_sessions (
    run_id       bigint   NOT NULL REFERENCES schedule_runs (id) ON DELETE CASCADE,
    section_id   integer  NOT NULL REFERENCES course_sections (id) ON DELETE CASCADE,
    idx          smallint NOT NULL CHECK (idx >= 0),               -- buổi thứ mấy trong tuần
    day          smallint NOT NULL CHECK (day BETWEEN 1 AND 6),
    start_period smallint NOT NULL CHECK (start_period BETWEEN 1 AND 12),
    length       smallint NOT NULL CHECK (length BETWEEN 2 AND 5),
    room_id      integer  REFERENCES rooms (id),                   -- NULL: không gán được phòng
    PRIMARY KEY (run_id, section_id, idx),
    -- H8: buổi học nằm trọn trong ca sáng (1-6) hoặc ca chiều (7-12)
    CONSTRAINT template_sessions_within_shift_ck
        CHECK (start_period + length - 1 <= 6
            OR (start_period >= 7 AND start_period + length - 1 <= 12))
);
CREATE INDEX template_sessions_day_idx  ON template_sessions (run_id, day);
CREATE INDEX template_sessions_room_idx ON template_sessions (run_id, room_id);

-- Giai đoạn 2: lịch thật theo ngày, gồm cả buổi học bù
CREATE TABLE calendar_sessions (
    run_id       bigint   NOT NULL REFERENCES schedule_runs (id) ON DELETE CASCADE,
    section_id   integer  NOT NULL REFERENCES course_sections (id) ON DELETE CASCADE,
    seq_no       smallint NOT NULL CHECK (seq_no >= 1),            -- buổi thứ mấy trong cả kỳ
    date         date     NOT NULL,
    start_period smallint NOT NULL CHECK (start_period BETWEEN 1 AND 12),
    length       smallint NOT NULL CHECK (length BETWEEN 2 AND 5), -- buổi cuối có thể ngắn hơn nhưng >= 2
    room_id      integer  REFERENCES rooms (id),
    lecturer_id  integer  NOT NULL REFERENCES lecturers (id),
    is_makeup    boolean  NOT NULL DEFAULT false,
    PRIMARY KEY (run_id, section_id, seq_no),
    CONSTRAINT calendar_sessions_weekday_ck
        CHECK (EXTRACT(ISODOW FROM date) BETWEEN 1 AND 6),        -- không học Chủ nhật
    CONSTRAINT calendar_sessions_within_shift_ck
        CHECK (start_period + length - 1 <= 6
            OR (start_period >= 7 AND start_period + length - 1 <= 12))
);
CREATE INDEX calendar_sessions_date_idx     ON calendar_sessions (run_id, date);
CREATE INDEX calendar_sessions_lecturer_idx ON calendar_sessions (run_id, lecturer_id, date);
CREATE INDEX calendar_sessions_room_idx     ON calendar_sessions (run_id, room_id, date);

-- Vi phạm ràng buộc của lịch kết quả, để giao diện giải thích
CREATE TABLE run_violations (
    id       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id   bigint NOT NULL REFERENCES schedule_runs (id) ON DELETE CASCADE,
    code     text   NOT NULL CHECK (code ~ '^[HS][0-9]+$'),       -- H1..H9, S1..S8
    severity text   NOT NULL CHECK (severity IN ('HARD', 'SOFT')),
    detail   jsonb  NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT run_violations_severity_ck
        CHECK ((severity = 'HARD') = (code LIKE 'H%'))
);
CREATE INDEX run_violations_run_idx ON run_violations (run_id, code);

COMMIT;
