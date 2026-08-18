(defun classify (x)
  (cond
    ((< x 0) "negative")
    ((> x 0) "positive")
    (t "zero")))

(defun max3 (a b c)
  (if (> a b)
    (if (> a c) a c)
    (if (> b c) b c)))

(defun is-even (n)
  (if (= n 0)
    t
    (is-odd (- n 1))))

(defun is-odd (n)
  (if (= n 0)
    nil
    (is-even (- n 1))))
