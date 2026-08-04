(defun max3 (a b c)
  (if (> a b)
    (if (> a c) a c)
    (if (> b c) b c)))
