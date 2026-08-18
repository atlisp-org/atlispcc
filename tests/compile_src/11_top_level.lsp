(setq *version* "1.0")
(princ "Loading library...")
(defun t10-init-hello () (princ "Hello from lib!"))
(defun get-version () *version*)
