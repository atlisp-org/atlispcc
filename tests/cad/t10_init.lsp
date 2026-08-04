(setq *version* "1.0")
(princ "Loading library...")
(defun hello () (princ "Hello from lib!"))
(defun get-version () *version*)
