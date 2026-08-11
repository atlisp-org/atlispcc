(defun *error* (msg)
  (setq t24-error-msg msg)
  msg)

(defun t24-handler-test ()
  (setq t24-error-msg nil)
  (*error* "handler-ran")
  t24-error-msg)
