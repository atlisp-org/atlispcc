(defun v-greet (name &optional greeting)
  (if greeting
    (strcat greeting ", " name "!")
    (strcat "Hello, " name "!")))

(defun v-sum-rest (first &rest rest)
  (apply '+ (cons first rest)))

(defun v-product (factor &rest rest)
  (if factor
    (* factor (apply '* rest))
    factor))

(defun v-first-arg (a &rest r)
  (if r (car r) a))

(defun v-pure-optional (&optional a b)
  (list a b))
