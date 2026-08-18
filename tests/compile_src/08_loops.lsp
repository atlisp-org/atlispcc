(defun sum-foreach (lst)
  (setq total 0)
  (foreach x lst
    (setq total (+ total x)))
  total)

(defun collect-foreach (lst / out)
  (setq out nil)
  (foreach x lst
    (setq out (cons (* x 2) out)))
  (reverse out))

(defun repeat-count (n)
  (setq acc 0)
  (repeat n
    (setq acc (1+ acc)))
  acc)
