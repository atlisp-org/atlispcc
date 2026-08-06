(defun t20-apply-fn (f x)
  (apply f (list x)))
(defun t20-kwote ()
  (t20-apply-fn
    (function (lambda (n) (* n 2)))
    21))
