(defun t19-greet (name &optional greeting)
  (if greeting
    (strcat greeting ", " name "!")
    (strcat "Hello, " name "!")))
(defun t19-sum (first &rest rest)
  (apply '+ (cons first rest)))
