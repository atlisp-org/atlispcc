(defun classify (x)
  (cond
    ((< x 0) "negative")
    ((> x 0) "positive")
    (t "zero")
  )
)
