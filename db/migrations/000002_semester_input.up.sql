-- Nhóm B: học kỳ và đầu vào xếp lịch
BEGIN;

CREATE TABLE semesters (
    id               integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name             text        NOT NULL UNIQUE,
    start_date       date        NOT NULL,
    end_date         date        NOT NULL,
    study_weeks      smallint    NOT NULL DEFAULT 15 CHECK (study_weeks > 0),
    exam_weeks       smallint    NOT NULL DEFAULT 3  CHECK (exam_weeks >= 0),
    -- Khoá ngoại tới schedule_runs được thêm ở migration 000003
    published_run_id bigint,
    created_at       timestamptz NOT NULL DEFAULT now(),
    -- Tuần mẫu tính từ Thứ 2, nên học kỳ phải bắt đầu vào Thứ 2
    CONSTRAINT semesters_start_monday_ck
        CHECK (EXTRACT(ISODOW FROM start_date) = 1),
    -- Đủ chỗ cho (study_weeks + exam_weeks) tuần, kết thúc sớm nhất vào Thứ 7 tuần cuối
    CONSTRAINT semesters_length_ck
        CHECK (end_date - start_date >= (study_weeks + exam_weeks) * 7 - 2)
);

-- Ngày lễ phải nằm trong khoảng học kỳ: kiểm tra ở tầng ứng dụng
CREATE TABLE semester_holidays (
    semester_id integer NOT NULL REFERENCES semesters (id) ON DELETE CASCADE,
    date        date    NOT NULL,
    name        text    NOT NULL,
    PRIMARY KEY (semester_id, date)
);

-- Học kỳ này lớp đang ở kỳ đào tạo nào
CREATE TABLE semester_classes (
    semester_id integer  NOT NULL REFERENCES semesters (id) ON DELETE CASCADE,
    class_id    integer  NOT NULL REFERENCES student_classes (id),
    term_no     smallint NOT NULL CHECK (term_no >= 1),
    PRIMARY KEY (semester_id, class_id)
);
CREATE INDEX semester_classes_class_idx ON semester_classes (class_id);

-- Lớp-môn: sinh tự động từ semester_classes x curriculum_items
CREATE TABLE course_sections (
    id          integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    semester_id integer NOT NULL,
    class_id    integer NOT NULL,
    subject_id  integer NOT NULL REFERENCES subjects (id),
    CONSTRAINT course_sections_uq UNIQUE (semester_id, class_id, subject_id),
    -- Lớp phải thuộc học kỳ này
    CONSTRAINT course_sections_semester_class_fk
        FOREIGN KEY (semester_id, class_id)
        REFERENCES semester_classes (semester_id, class_id) ON DELETE CASCADE
);
CREATE INDEX course_sections_subject_idx ON course_sections (subject_id);

COMMIT;
