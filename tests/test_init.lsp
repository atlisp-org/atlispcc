(princ "Loading my-library...")

(setq *version* "1.0")

(defun hello ()
  (princ "Hello from my-library!")
)

(defun greet (name)
  (princ (strcat "Hello, " name "!"))
)
