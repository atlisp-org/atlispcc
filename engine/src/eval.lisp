;;;; eval.lisp — 求值器
;;;;
;;;; 自左而右求值，特殊形式表驱动。动态作用域（见 env.lisp）。
;;;; defun/参数解析支持：&optional、&rest、/ 局部变量、lambda、apply/funcall/mapcar。
(in-package #:atlisp)

(defvar *quote-sym* (al-int "QUOTE"))
(defvar *function-sym* (al-int "FUNCTION"))
(defvar *lambda-sym* (al-int "LAMBDA"))
(defvar *defun-sym* (al-int "DEFUN"))
(defvar *if-sym-* (al-int "IF"))
(defvar *t-sym* (al-int "T"))
(defvar *nil-sym* (al-int "NIL"))

(defparameter *special-forms*
  (mapcar #'al-int
          '("QUOTE" "FUNCTION" "IF" "WHILE" "FOREACH" "REPEAT" "COND"
            "PROGN" "SETQ" "AND" "OR" "DEFUN"))
  "特殊形式（不求值所有参数）符号集。")

(defun special-form-p (sym) (member sym *special-forms* :test #'eq))

;;; ── 顶层求值 ──────────────────────────────────────────────────────────────

(defun al-eval-form (form)
  "求值一个 AutoLISP 表达式（datum → value）。"
  (cond
    ((null form) nil)
    ((eq form t) t)
    ((symbolp form) (al-value-symbol form))
    ((numberp form) form)
    ((stringp form) form)
    ((al-cons-p form) (al-eval-cons form))
    (t form)))

(defun al-value-symbol (sym)
  "符号求值：T→t、NIL→nil（AutoLISP 常量）；否则先按变量取，未绑定变量时
   若为函数名则返回函数对象（apply/mapcar 未加引号时）。"
  (cond
    ((eq sym *nil-sym*) nil)
    ((eq sym *t-sym*) t)
    (t (al-value sym))))

(defun al-eval-source (source)
  "解析并顺序求值整个源码，返回最后一个形式的值。"
  (let ((last nil))
    (dolist (f (al-read-source source) last)
      (setf last (al-eval-form f)))))

(defun al-eval-forms (forms)
  "顺序求值 forms，返回最后一个值（空 → nil）。"
  (let ((last nil))
    (dolist (f forms last)
      (setf last (al-eval-form f)))))

;;; ── 组合式求值 ────────────────────────────────────────────────────────────

(defun al-eval-cons (form)
  (let ((head (car form))
        (args (cdr form)))
    (cond
      ((and (symbolp head) (special-form-p head))
       (al-eval-special head args))
      ((and (al-cons-p head)
            (eq (car head) *lambda-sym*))
       ;; ((lambda (x) body) arg...) 直接调用
       (let ((fn (al-lambda-form->fn head))
             (evals (mapcar #'al-eval-form args)))
         (al-call fn evals)))
      (t
       (let ((fn (al-eval-function-head head))
             (evals (mapcar #'al-eval-form args)))
         (al-call fn evals))))))

(defun al-eval-function-head (head)
  "求值调用头：符号（函数名）或 (function ...) / '(lambda ...) 形式。"
  (cond
    ((symbolp head)
     ;; 类型子 / 普通函数名
     (let ((f (al-lookup-fn head)))
       (cond
         (f f)
         ((gethash head *builtin-table*) (gethash head *builtin-table*))
         (t (let ((v (al-value head)))
              (if (or (fn-p v) (subr-p v)) v nil))))))
    ((al-cons-p head)
     (cond
       ((eq (car head) *function-sym*)
        (al-as-function (cadr head)))
       ((eq (car head) *quote-sym*)
        (al-as-function (cadr head)))
       ((eq (car head) *lambda-sym*)
        (al-lambda-form->fn head))
       (t (al-as-function (al-eval-form head)))))
    (t (al-as-function (al-eval-form head)))))

(defun al-eval-function-expr (fn-form)
  "把 (function f) 的 f 转成可调用对象。"
  (al-as-function fn-form))

(defun al-as-function (datum)
  "把任意 datum 规范化为可调用对象：fn/subr/符号/lambda 形式/带引号 lambda。"
  (cond
    ((fn-p datum) datum)
    ((subr-p datum) datum)
    ((symbolp datum)
     (or (al-lookup-fn datum)
         (gethash datum *builtin-table*)
         nil))
    ((al-cons-p datum)
     (cond
       ((eq (car datum) *quote-sym*) (al-as-function (cadr datum)))
       ((eq (car datum) *function-sym*) (al-as-function (cadr datum)))
       ((eq (car datum) *lambda-sym*) (al-lambda-form->fn datum))
       (t (al-as-function (al-eval-form datum)))))
    (t nil)))

(defun al-lambda-form->fn (form)
  "(lambda (args...) body...) → fn"
  (make-fn :name nil :args (cadr form) :body (cddr form) :islambda t))

(defun al-call (fn args)
  "以 args 列表调用 fn。"
  (cond
    ((subr-p fn) (funcall (subr-fn fn) args))
    ((fn-p fn) (al-apply-user-fn fn args))
    (t (error "Attempt to call non-function: ~a" fn))))

;;; ── 特殊形式 ──────────────────────────────────────────────────────────────

(defun al-eval-special (op args)
  (ecase op
    (al::QUOTE (car args))
    (al::FUNCTION (al-as-function (car args)))
    (al::IF (al-eval-if args))
    (al::WHILE (al-eval-while args))
    (al::FOREACH (al-eval-foreach args))
    (al::REPEAT (al-eval-repeat args))
    (al::COND (al-eval-cond args))
    (al::PROGN (al-eval-forms args))
    (al::SETQ (al-eval-setq args))
    (al::AND (al-eval-and args))
    (al::OR (al-eval-or args))
    (al::DEFUN (al-eval-defun args))))

(defun al-eval-if (args)
  (if (al-eval-form (nth 0 args))
      (if (nth 1 args) (al-eval-form (nth 1 args)) nil)
      (if (nth 2 args) (al-eval-form (nth 2 args)) nil)))

(defun al-eval-while (args)
  (let ((cond (first args))
        (body (rest args)))
    (loop while (al-eval-form cond)
          do (al-eval-forms body))
    nil))

(defun al-eval-foreach (args)
  (let ((var (first args))
        (list-form (second args))
        (body (cddr args)))
    (let ((lst (al-eval-form list-form)))
      (dolist (item lst nil)
        (al-bind var item)
        (unwind-protect (al-eval-forms body)
          (al-unbind var))))))

(defun al-eval-repeat (args)
  (let ((n (al-eval-form (first args)))
        (body (rest args)))
    (if (not (integerp n)) (setf n (floor n)))
    (dotimes (i n nil) (declare (ignore i)) (al-eval-forms body))))

(defun al-eval-cond (args)
  (dolist (clause args nil)
    (let ((test (first clause))
          (body (rest clause)))
      (when (or (eq test t)
                (eq test *t-sym*)
                (al-eval-form test))
        (return (if body (al-eval-forms body) (or (and (eq test t) t) (and (eq test *t-sym*) t) (al-eval-form test))))))))

(defun al-eval-setq (args)
  "SETQ 变参成对：先求值后绑定，支持多对 (setq a 1 b 2)。"
  (let ((last nil))
    (loop for (var val) on args by #'cddr
          when val
          do (setf last (al-eval-form val))
             (al-setq var last))
    last))

(defun al-eval-and (args)
  (if (null args)
      t
      (let ((last t))
        (dolist (f args nil)
          (setf last (al-eval-form f))
          (when (null last) (return nil)))
        last)))

(defun al-eval-or (args)
  (dolist (f args nil)
    (let ((v (al-eval-form f)))
      (when v (return v)))))

;;; ── defun / 参数 ──────────────────────────────────────────────────────────

(defun al-sym-eq (a b)
  "两个 AL 符号或字符串名相等（大小写不敏感由 reader 统一大写保证）。"
  (eq a b))

(defstruct (arg-spec (:constructor make-arg-spec (required optional rest locals)))
  "解析后的参数规格。"
  required         ; 必选参数符号表
  optional         ; &optional 参数符号表
  rest             ; &rest 符号或 nil
  locals)          ; / 局部变量符号表

(defun parse-arglist (arglist)
  "defun/lambda 参数表 → arg-spec。arglist 为 (读入后的符号列表或 nil，含 &optional/&rest//)。
   注意：nil 参数表用 nil 表示（不能直接 (arglist)…），解析时容忍。"
  (let ((required '())
        (optional '())
        (rest nil)
        (locals '())
        (mode :required))
    (dolist (sym arglist)
      (cond
        ((string-equal (symbol-name sym) "&OPTIONAL")
         (setf mode :optional))
        ((string-equal (symbol-name sym) "&REST")
         (setf mode :rest))
        ((string-equal (symbol-name sym) "/")
         (setf mode :locals))
        (t
         (ecase mode
           (:required (push sym required))
           (:optional (push sym optional))
           (:rest (setf rest sym) (setf mode :locals-rest))
           ((:locals :locals-rest) (push sym locals))))))
    (make-arg-spec (nreverse required) (nreverse optional)
                   rest (nreverse locals))))

(defun al-eval-defun (args)
  (let ((name (first args))
        (arglist (second args))
        (body (cddr args)))
    (unless (symbolp name) (error "defun name must be a symbol: ~a" name))
    (let ((spec (parse-arglist arglist)))
      (al-register-fn name (make-fn :name name :args arglist :body body))
      name)))

;;; ── 用户函数调用（动态作用域） ──────────────────────────────────────────────

(defun al-apply-user-fn (fn args)
  (let* ((spec (parse-arglist (fn-args fn)))
         (n-req (length (arg-spec-required spec)))
         (n-opt (length (arg-spec-optional spec)))
         (n-args (length args)))
    (when (< n-args n-req)
      (error "Too few arguments for ~a: need at least ~d, got ~d"
             (or (fn-name fn) "lambda") n-req n-args))
    (let ((locals (arg-spec-locals spec))
          (req-syms (arg-spec-required spec))
          (opt-syms (arg-spec-optional spec))
          (rest-sym (arg-spec-rest spec)))
    
      ;; 处理剩余参数：&rest 收集，或触发多余参数错误
      (let ((binds '()))
        (loop for i below (length req-syms) do
          (push (cons (nth i req-syms) (nth i args)) binds))
        (let ((avail (nthcdr n-req args)))
          (when opt-syms
            (loop for i below (length opt-syms) do
              (let ((sym (nth i opt-syms)))
                (push (cons sym (if (< i (length avail)) (nth i avail) nil)) binds))))
          (let ((after-opt (nthcdr n-opt avail)))
            (cond
              (rest-sym (push (cons rest-sym after-opt) binds))
              (after-opt (error "Too many arguments for ~a: got ~d"
                                (or (fn-name fn) "lambda") n-args)))))
        ;; / locals → nil
        (dolist (l locals) (push (cons l nil) binds))
        ;; 绑定全部，求值 body，确保 unwind
        (let ((bound (mapcar #'car binds)))
          (dolist (b binds) (al-bind (car b) (cdr b)))
          (unwind-protect (al-eval-forms (fn-body fn))
            (al-unbind-all bound)))))))
