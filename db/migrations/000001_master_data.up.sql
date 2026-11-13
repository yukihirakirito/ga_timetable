-- Nhóm A: dữ liệu danh mục (Go CRUD)
BEGIN;

CREATE TABLE departments (
    id   integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code text NOT NULL UNIQUE,
    name text NOT NULL
);

CREATE TABLE majors (
    id   integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code text NOT NULL UNIQUE,
    name text NOT NULL
);

CREATE TABLE room_types (
    code text PRIMARY KEY,
    name text NOT NULL
);

INSERT INTO room_types (code, name) VALUES
    ('THEORY', 'Phòng lý thuyết'),
    ('LAB',    'Phòng máy tính'),
    ('STUDIO', 'Phòng studio');

-- Bảng quy đổi tín chỉ -> lịch học. 1 TC = 15 tiết, học kỳ 15 tuần học.
CREATE TABLE credit_rules (
    credits             smallint PRIMARY KEY CHECK (credits BETWEEN 1 AND 5),
    periods_per_session smallint NOT NULL CHECK (periods_per_session BETWEEN 2 AND 5),
    sessions_per_week   smallint NOT NULL CHECK (sessions_per_week BETWEEN 1 AND 6),
    -- Môn >= 4 TC: mỗi buổi ít nhất 3 tiết
    CONSTRAINT credit_rules_min_length_ck
        CHECK (credits < 4 OR periods_per_session >= 3),
    -- Chia hết, hoặc buổi cuối vẫn >= 2 tiết
    CONSTRAINT credit_rules_last_session_ck
        CHECK ((credits * 15) % periods_per_session = 0
            OR (credits * 15) % periods_per_session >= 2),
    -- Học xong trong 15 tuần: ceil(ceil(tiết / tiết_buổi) / buổi_tuần) <= 15
    CONSTRAINT credit_rules_fits_term_ck
        CHECK ((((credits * 15) + periods_per_session - 1) / periods_per_session
                + sessions_per_week - 1) / sessions_per_week <= 15)
);

INSERT INTO credit_rules (credits, periods_per_session, sessions_per_week) VALUES
    (1, 3, 1),
    (2, 3, 1),
    (3, 3, 2),
    (4, 4, 2),
    (5, 5, 2);

CREATE TABLE subjects (
    id            integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code          text     NOT NULL UNIQUE,
    name          text     NOT NULL,
    credits       smallint NOT NULL REFERENCES credit_rules (credits),
    room_type     text     NOT NULL REFERENCES room_types (code),
    department_id integer  NOT NULL REFERENCES departments (id)
);
CREATE INDEX subjects_department_idx ON subjects (department_id);

-- Chương trình đào tạo: ngành học môn nào ở kỳ đào tạo nào
CREATE TABLE curriculum_items (
    major_id   integer  NOT NULL REFERENCES majors (id) ON DELETE CASCADE,
    term_no    smallint NOT NULL CHECK (term_no >= 1),
    subject_id integer  NOT NULL REFERENCES subjects (id),
    PRIMARY KEY (major_id, term_no, subject_id)
);
CREATE INDEX curriculum_items_subject_idx ON curriculum_items (subject_id);

CREATE TABLE rooms (
    id        integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code      text    NOT NULL UNIQUE,
    room_type text    NOT NULL REFERENCES room_types (code),
    capacity  integer NOT NULL CHECK (capacity > 0)
);
CREATE INDEX rooms_type_idx ON rooms (room_type);

CREATE TABLE lecturers (
    id                   integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code                 text     NOT NULL UNIQUE,
    name                 text     NOT NULL,
    department_id        integer  NOT NULL REFERENCES departments (id),
    -- Ràng buộc mềm S8; 72 = 6 ngày x 12 tiết
    max_periods_per_week smallint NOT NULL DEFAULT 20
        CHECK (max_periods_per_week BETWEEN 1 AND 72)
);
CREATE INDEX lecturers_department_idx ON lecturers (department_id);

-- Giảng viên dạy được môn nào (H7: miền giá trị gen giảng viên)
CREATE TABLE lecturer_subjects (
    lecturer_id integer NOT NULL REFERENCES lecturers (id) ON DELETE CASCADE,
    subject_id  integer NOT NULL REFERENCES subjects (id) ON DELETE CASCADE,
    PRIMARY KEY (lecturer_id, subject_id)
);
CREATE INDEX lecturer_subjects_subject_idx ON lecturer_subjects (subject_id);

-- Khung giờ bận (H5) / ưu tiên (S5) của giảng viên, theo tuần mẫu
CREATE TABLE lecturer_slots (
    id          integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    lecturer_id integer  NOT NULL REFERENCES lecturers (id) ON DELETE CASCADE,
    day         smallint NOT NULL CHECK (day BETWEEN 1 AND 6),       -- 1 = Thứ 2 ... 6 = Thứ 7
    period_from smallint NOT NULL CHECK (period_from BETWEEN 1 AND 12),
    period_to   smallint NOT NULL CHECK (period_to BETWEEN 1 AND 12),
    kind        text     NOT NULL CHECK (kind IN ('UNAVAILABLE', 'PREFERRED')),
    CONSTRAINT lecturer_slots_range_ck CHECK (period_from <= period_to)
);
CREATE INDEX lecturer_slots_lecturer_idx ON lecturer_slots (lecturer_id);

CREATE TABLE student_classes (
    id       integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code     text    NOT NULL UNIQUE,
    major_id integer NOT NULL REFERENCES majors (id),
    size     integer NOT NULL CHECK (size > 0)
);
CREATE INDEX student_classes_major_idx ON student_classes (major_id);

COMMIT;
