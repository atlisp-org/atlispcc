(defun factorial (n)
  (if (<= n 1)
    1
    (* n (factorial (- n 1)))))

(defun fibonacci (n)
  (if (< n 2)
    n
    (+ (fibonacci (- n 1)) (fibonacci (- n 2)))))
