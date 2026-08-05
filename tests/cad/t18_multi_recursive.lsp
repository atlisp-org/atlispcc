(defun is-even (n)
  (if (= n 0)
    t
    (is-odd (- n 1))))
(defun is-odd (n)
  (if (= n 0)
    nil
    (is-even (- n 1))))
