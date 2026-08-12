;;; engine_smoke.lsp — engine 冒烟自检（P1 对拍基线）
;;;
;;; 纯 AutoLISP 实现。覆盖：算术/递归/if/while/cond/局部变量/foreach/repeat/
;;; &optional/&rest/kwote-mapcar/dotted/strcat/geometry/T-NIL/互递归/apply/funcall。
;;; 运行：sbcl 加载 atlisp.asd 后 (al-run-file "engine/engine_smoke.lsp")，
;;; 期望全部 `S#=OK` 且末尾 `SMOKE-DONE`。

(defun smoke-report (name val expected)
  (princ name) (princ "=")
  (if (equal val expected)
      (princ "OK")
      (progn (princ "FAIL got ") (princ val) (princ " expected ") (princ expected)))
  (terpri))

;; 算术 / 递归
(defun sf (n) (if (<= n 1) 1 (* n (sf (- n 1)))))
(smoke-report "S1" (sf 5) 120)

;; &optional
(defun sg (a &optional b) (if b (+ a b) a))
(smoke-report "S2" (list (sg 3) (sg 3 4)) (list 3 7))

;; &rest
(defun sh (a &rest r) (apply '+ (cons a r)))
(smoke-report "S3" (sh 1 2 3 4) 10)

;; foreach + / 局部变量
(defun sforeach (lst / total)
  (setq total 0)
  (foreach x lst (setq total (+ total x)))
  total)
(smoke-report "S4" (sforeach (quote (1 2 3 4))) 10)

;; repeat
(defun srep (n) (setq acc 0) (repeat n (setq acc (1+ acc))) acc)
(smoke-report "S5" (srep 5) 5)

;; cond else 键 (t ...)
(defun scond (x) (cond ((< x 0) "neg") ((> x 0) "pos") (t "zero")))
(smoke-report "S6" (list (scond -1) (scond 0) (scond 1)) (list "neg" "zero" "pos"))

;; 几何 distance（car 应为 5.0）
(defun sp (a b) (distance a b))
(smoke-report "S7" (fix (sp (quote (0 0)) (quote (3 4)))) 5)

;; kwote mapcar
(defun slam () (mapcar (function (lambda (x) (* x 3))) (quote (1 2))))
(smoke-report "S8" (slam) (list 3 6))

;; dotted quote
(defun sdot () (quote (1 . 2)))
(smoke-report "S9" (list (car (sdot)) (cdr (sdot))) (list 1 2))

;; strcat
(smoke-report "S10" (strcat "a" "b" "c") "abc")

;; while
(defun sw () (setq i 0) (while (< i 3) (setq i (1+ i))) i)
(smoke-report "S11" (sw) 3)

;; T/NIL 常量
(smoke-report "S12" (list (if t "yes" "no") (if nil "yes" "no")) (list "yes" "no"))

;; 互递归
(defun seven (n) (if (= n 0) t (sodd (- n 1))))
(defun sodd (n) (if (= n 0) nil (seven (- n 1))))
(smoke-report "S13" (seven 4) t)
(smoke-report "S14" (sodd 3) t)

;; apply / funcall
(smoke-report "S15" (apply '+ (quote (1 2 3 4))) 10)
(smoke-report "S16" (funcall (function (lambda (x) (* x 2))) 21) 42)

;; list / append / reverse
(smoke-report "S17" (reverse (append (quote (1 2)) (quote (3 4)))) (list 4 3 2 1))

(princ "SMOKE-DONE") (terpri)
