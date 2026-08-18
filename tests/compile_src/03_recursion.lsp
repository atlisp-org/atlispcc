(defun factorial (n)
  (if (<= n 1)
    1
    (* n (factorial (- n 1)))))

(defun fib (n)
  (if (< n 2)
    n
    (+ (fib (- n 1)) (fib (- n 2)))))

(defun count-to (n / acc)
  (setq acc 0)
  (while (< acc n)
    (setq acc (1+ acc)))
  acc)
