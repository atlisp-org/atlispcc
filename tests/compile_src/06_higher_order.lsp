(defun sum-list (lst)
  (apply '+ lst))

(defun double-all (lst)
  (mapcar '(lambda (x) (* x 2)) lst))

(defun apply-fn (f x)
  (apply f (list x)))

(defun kwote-double ()
  (apply-fn
    (function (lambda (n) (* n 2)))
    21))
