(defun sum-foreach (lst)
  (setq total 0)
  (foreach x lst
    (setq total (+ total x)))
  total)
