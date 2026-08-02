(defun cad-factorial (n / result)
  (if (<= n 1)
    (setq result 1)
    (setq result (* n (cad-factorial (- n 1))))
  )
  result
)

(defun cad-fibonacci (n)
  (if (< n 2)
    n
    (+ (cad-fibonacci (- n 1)) (cad-fibonacci (- n 2)))
  )
)

(defun cad-sum-list (lst / total i item)
  (setq total 0)
  (setq i 0)
  (while (< i (length lst))
    (setq item (nth i lst))
    (if (numberp item)
      (setq total (+ total item))
    )
    (setq i (1+ i))
  )
  total
)

(defun cad-str-repeat (s n / result)
  (setq result "")
  (repeat n
    (setq result (strcat result s))
  )
  result
)

(defun cad-filter-positive (lst / result i item)
  (setq result (list))
  (setq i 0)
  (while (< i (length lst))
    (setq item (nth i lst))
    (if (> item 0)
      (setq result (append result (list item)))
    )
    (setq i (1+ i))
  )
  result
)

(defun cad-classify (x)
  (cond
    ((< x 0) "negative")
    ((= x 0) "zero")
    ((> x 0) "positive")
  )
)

(defun cad-gcd (a b)
  (if (= b 0)
    a
    (cad-gcd b (rem a b))
  )
)

(defun cad-is-prime (n / i limit)
  (if (< n 2)
    nil
    (progn
      (setq i 2)
      (setq limit (fix (sqrt n)))
      (setq result T)
      (while (and (<= i limit) result)
        (if (= (rem n i) 0)
          (setq result nil)
        )
        (setq i (1+ i))
      )
      result
    )
  )
)

(defun cad-map-double (lst)
  (mapcar '(lambda (x) (* x 2)) lst)
)

(defun cad-foreach-sum (lst / total)
  (setq total 0)
  (foreach x lst
    (setq total (+ total x))
  )
  total
)

(defun cad-apply-max (lst)
  (if (not lst)
    nil
    (apply 'max lst)
  )
)

(defun cad-and-or-test (a b c)
  (and (> a 0) (< a 100) (or (= b 0) (> b 10)) (not (= c nil)))
)

(defun cad-nested-if (a b c)
  (if (> a 0)
    (if (> b 0)
      (if (> c 0)
        "all-positive"
        "c-not-positive"
      )
      "b-not-positive"
    )
    "a-not-positive"
  )
)

(princ "CAD complex test functions loaded.")
(princ)
