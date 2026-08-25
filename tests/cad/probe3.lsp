(defun foo ()
  (bar)
  (boundp 'bar))
(defun bar () 1)
