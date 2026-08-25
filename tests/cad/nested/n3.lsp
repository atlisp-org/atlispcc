(defun n3-outer (/ seen)
  (defun n3-inner (name)
    (if (not (member name seen))
      (progn
        (setq seen (cons name seen))
        name)))
  (setq seen nil)
  (n3-inner 'a)
  (n3-inner 'b))
