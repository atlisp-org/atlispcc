;; Auto-decompiled from t11_localvars_cad.fas
;; Generated AutoLISP output

(defun sum-to-n (i / result)
  (_al-bind-alist '(result i))
  (setq result 0)
  (setq i 1)
  (while (<= i i)
    (setq result (+ result i))
    (setq i (+ i 1))
  )
  result
)
