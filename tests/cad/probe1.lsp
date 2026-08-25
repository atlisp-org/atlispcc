(defun foo ()
  (if (boundp 'bar) (bar) nil))
(defun bar () 1)
