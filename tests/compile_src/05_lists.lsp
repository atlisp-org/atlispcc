(defun get-first (lst)
  (car lst))

(defun get-rest (lst)
  (cdr lst))

(defun build-list ()
  (list 1 2 3))

(defun pair (a b)
  (cons a b))

(defun test-quote ()
  (setq lst '(a b c)))

(defun test-cons-quote ()
  '(1 . 2))

(defun test-nested-quote ()
  (quote (1 2 3)))
