(defun n1-outer ()
  (defun n1-inner ()
    42)
  (n1-inner))
