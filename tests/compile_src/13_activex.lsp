(defun t22-acad-doc ()
  (vla-get-ActiveDocument (vlax-get-acad-object)))

(defun t22-has-active-doc ()
  (if (t22-acad-doc) T nil))

(defun t22-get-modelspace (doc)
  (vla-get-ModelSpace doc))

(defun t22-doc-count (acad)
  (vla-get-count (vla-get-Documents acad)))

(defun t22-positive-count (acad)
  (if (> (t22-doc-count acad) 0) T nil))
