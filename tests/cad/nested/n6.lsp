(defun n6-outer (flag)
  (if flag
    (defun n6-inner ()
      t))
  (if flag (n6-inner) nil))
