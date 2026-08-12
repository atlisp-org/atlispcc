;;;; values.lisp — 运行时值模型
;;;;
;;;; AutoLISP 数据直接映射到 CL 原生值：
;;;;   空表/空列表 → nil；真值 → t；整数 → CL 整数（运算时按 32 位回绕）
;;;;   浮点 → double-float；字符串 → CL string；符号数据 → AL 包 symbol
;;;;   表/cons/dotted → CL cons
;;;;
;;;; 函数对象（用户函数/内建）用 defstruct 表示。
(in-package #:atlisp)

(declaim (inline al-int al-sym-p))

(defun al-int (name)
  "把 AutoLISP 符号名统一大写后 intern 到 AL 包（大小写不敏感）。"
  (intern (string-upcase (string name)) :al))

;;; ── 函数对象 ──────────────────────────────────────────────────────────────

(defstruct (fn (:constructor make-fn))
  "用户定义函数（defun 或 (function (lambda ...)))。
   ARGS   : 参数符号（保留 &optional/&rest 与 / 局部变量分隔符）
   BODY   : 函数体形式列表
   ISLAMBDA : t 表示匿名 lambda（经 (function (lambda ...)) / quote）"
  name
  args
  body
  (islambda nil))

(defstruct (subr (:constructor make-subr))
  "内建函数：NAME 为 AL 符号，FN 为 (lambda (args) value) 接受的 CL 函数。"
  name
  fn)

;;; ── 其它运行对象 ──────────────────────────────────────────────────────────

(defstruct (file-obj (:constructor make-file-obj))
  "AutoLISP 文件流对象（封装 CL stream）。"
  stream
  mode)

(defstruct (cad-stub (:constructor make-cad-stub))
  "CAD 专属对象占位（entget/vla-*/DCL…）：引擎外使用即报错。"
  kind
  detail)

;;; ── 判断/构造辅助 ─────────────────────────────────────────────────────────

(declaim (inline al-cons-p))
(defun al-cons-p (x) (consp x))

(declaim (inline al-list-p))
(defun al-list-p (x) (or (null x) (consp x)))

(defun al-print (x &optional (stream *standard-output*))
  "把运行时值打印成 AutoLISP 字面形式（princ 的输出格式）。"
  (cond
    ((null x) (princ "nil" stream))
    ((eq x t) (princ "T" stream))
    ((integerp x) (princ x stream))
    ((floatp x) (format stream "~,12F" x))
    ((stringp x) (princ x stream))
    ((symbolp x) (princ (symbol-name x) stream))
    ((file-obj-p x) (princ (format nil "#<file ~a>" (file-obj-stream x)) stream))
    ((fn-p x) (princ (format nil "#<function ~a>" (if (fn-name x) (fn-name x) "LAMBDA")) stream))
    ((subr-p x) (princ (format nil "#<subr ~a>" (subr-name x)) stream))
    ((cad-stub-p x) (princ (format nil "#<~a>" (cad-stub-kind x)) stream))
    ((al-cons-p x) (al-print-cons x stream))
    (t (write x :stream stream :escape nil))))

(defun al-print-cons (x stream)
  "按 AutoLISP 表/dotted 语法打印 cons 链。"
  (princ "(" stream)
  (loop
    (al-print (car x) stream)
    (cond
      ((null (cdr x)) (return))
      ((al-cons-p (cdr x)) (princ " " stream) (setf x (cdr x)))
      (t (princ " . " stream) (al-print (cdr x) stream) (return))))
  (princ ")" stream))

(defun al-to-string (x)
  "princ 到字符串（princ 语义：字符串/数据不附加引号）。"
  (with-output-to-string (s) (al-print x s)))