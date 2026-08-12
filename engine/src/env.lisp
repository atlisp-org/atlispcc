;;;; env.lisp — 动态作用域环境
;;;;
;;;; AutoLISP 是运行时动态作用域：函数参数与 / 局部变量在调用期间可见于
;;;; 被调函数（被调函数没自己的同名绑定时）。实现为「每符号绑定栈」：
;;;;   调用函数时 push 参数/locals，返回时 pop；未被动态绑定的符号读/写全局表。
;;;; 未定义变量求值 = nil（AutoLISP 语义，非报错）。
(in-package #:atlisp)

(defvar *global-vals* (make-hash-table :test #'eq))
(defvar *global-fns* (make-hash-table :test #'eq))
;; symbol → 值栈（动态绑定用）
(defvar *dyn-bindings* (make-hash-table :test #'eq))

;;; ── 变量读写 ──────────────────────────────────────────────────────────────

(defun al-value (sym)
  "取符号当前值：动态绑定栈顶 → 全局 → nil（未定义 → nil）。"
  (let ((stack (gethash sym *dyn-bindings*)))
    (if stack
        (car stack)
        (gethash sym *global-vals* nil))))

(defun al-setq (sym val)
  "setq：改最近绑定（栈顶）；无动态绑定时写全局。"
  (let ((stack (gethash sym *dyn-bindings*)))
    (if stack
        (setf (car stack) val)
        (setf (gethash sym *global-vals*) val))))

(defun al-bind (sym val)
  "动态绑定：把 val 压到 sym 的绑定栈。"
  (push val (gethash sym *dyn-bindings*)))

(defun al-unbind (sym)
  "撤销一次动态绑定。"
  (let ((stack (gethash sym *dyn-bindings*)))
    (when stack (pop (gethash sym *dyn-bindings*)))))

;;; ── 函数表 ────────────────────────────────────────────────────────────────

(defun al-register-fn (sym fnobj)
  (setf (gethash sym *global-fns*) fnobj))

(defun al-lookup-fn (sym)
  (values (gethash sym *global-fns* nil)))

(defun al-unbind-all (syms)
  (dolist (s syms) (al-unbind s)))

(defun al-reset-all ()
  "清空全局环境（测试用）。"
  (clrhash *global-vals*)
  (clrhash *global-fns*)
  (clrhash *dyn-bindings*))
