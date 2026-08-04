(defun sum-list (lst)
  (apply '+ lst))
(defun double-all (lst)
  (mapcar '(lambda (x) (* x 2)) lst))
