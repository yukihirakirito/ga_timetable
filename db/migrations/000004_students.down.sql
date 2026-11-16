BEGIN;

-- Khôi phục cột sĩ số từ số sinh viên (lớp chưa có sinh viên thì để 1 cho qua CHECK size > 0)
ALTER TABLE student_classes ADD COLUMN size integer;
UPDATE student_classes c
   SET size = GREATEST(1, (SELECT count(*) FROM students s WHERE s.class_id = c.id));
ALTER TABLE student_classes
    ALTER COLUMN size SET NOT NULL,
    ADD CONSTRAINT student_classes_size_check CHECK (size > 0);

DROP TABLE extra_enrollments;
DROP TABLE students;

COMMIT;
