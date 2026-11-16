-- Sinh viên thật (M8a): sinh viên thuộc một lớp, học toàn bộ lớp-môn của lớp mình,
-- cộng các lớp-môn học thêm ở lớp khác (học lại, học ghép). Ràng buộc H10: không trùng lịch theo sinh viên.
BEGIN;

CREATE TABLE students (
    id       integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code     text    NOT NULL UNIQUE,
    name     text    NOT NULL,
    class_id integer NOT NULL REFERENCES student_classes (id)
);
CREATE INDEX students_class_idx ON students (class_id);

-- Chỉ lưu phần học thêm; phần học theo lớp là mặc định, không lưu từng dòng.
-- "Không học thêm lớp-môn của chính lớp mình" so sánh dữ liệu hai bảng nên không viết được bằng CHECK:
-- kiểm tra ở tầng ứng dụng (Go) và trong contracts/validate.py.
CREATE TABLE extra_enrollments (
    section_id integer NOT NULL REFERENCES course_sections (id) ON DELETE CASCADE,
    student_id integer NOT NULL REFERENCES students (id) ON DELETE CASCADE,
    PRIMARY KEY (section_id, student_id)
);
CREATE INDEX extra_enrollments_student_idx ON extra_enrollments (student_id);

-- Sĩ số lớp = số sinh viên, đếm từ bảng students (một nguồn sự thật duy nhất).
-- Dữ liệu sĩ số cũ bị bỏ: nạp lại seed sau khi chạy migration này.
ALTER TABLE student_classes DROP COLUMN size;

COMMIT;
