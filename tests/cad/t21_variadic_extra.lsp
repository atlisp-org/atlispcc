(defun t21-greet (name &optional greeting)
  (if greeting
    (strcat greeting ", " name "!")
    (strcat "Hello, " name "!")))

(defun t21-sum-rest (first &rest rest)
  (apply '+ (cons first rest)))

(defun t21-product (&optional factor &rest rest)
  (if factor
    (* factor (apply '* rest))
    factor))

(defun t21-first-arg (a &rest r)
  (if r (car r) a))
