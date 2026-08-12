;;;; packages.lisp — 包定义
;;;;
;;;; * ATLISP      : 引擎实现代码所在的 CL 包
;;;; * AL          : AutoLISP 符号包（源码符号一律大写 intern 于此，
;;;;                 与 CL 符号天然隔离，杜绝包名冲突）
(in-package #:cl-user)

(defpackage #:atlisp
  (:use #:cl)
  (:export
   ;; 公共 API
   #:al-read-source
   #:al-eval-form
   #:al-eval-source
   #:al-run-file
   #:al-repl
   #:al-int
   #:*load-exit-code*))

;; AutoLISP 符号包：大小写不敏感（统一大写），不含任何 CL 暴露符号
(defpackage #:al
  (:use))