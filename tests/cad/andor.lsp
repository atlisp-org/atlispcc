(defun test-andor (a b)
  (if (and (or (= a 1) (= b 2)) (> a 0))
    "yes"
    "no"))
