;; Auto-decompiled from t11_localvars_cad.fas
;; Generated AutoLISP output

(defun sum-to-n (n / result i)
  (_al-bind-alist '(result i))
  (while (<= i n)
    (setq result (+ result i))
    (setq i (+ i 1))
  )
  (setq result 0)
  (setq i 1)
  result
)
