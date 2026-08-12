;;;; builtins.lisp — 内建函数注册
;;;;
;;;; 所有 subr 都是 (lambda (args-literal-list) value)，args 为求值后的实参列表。
;;;;
;;;; M1 /* 基础：
;;;;   算术 / 比较 / 谓词 / cons 与列表 / 字符串 / 类型 / 输入输出 / apply+mapcar+eval。
;;;;   数字语义：整数按 32 位有符号回绕，双精度浮点参与即转浮点。
(in-package #:atlisp)

;;; – 注册表：AL 符号 → subr 对象
(defvar *builtin-table* (make-hash-table :test #'eq))

(defun register-subr (name cl-fn)
  "以 AutoLISP 名注册 CL 函数。cl-fn 形如 (lambda (args) value)。"
  (let ((sym (al-int name)))
    (setf (gethash sym *builtin-table*)
          (make-subr :name sym :fn cl-fn))
    sym))

(defmacro defsubr (name (args-var) &body body)
  "定义 AutoLISP 内建：实参列表绑定到 ARGS-VAR。"
  `(register-subr ,name (lambda (,args-var) ,@body)))

;;; ── 数字工具 ────────────────────────────────────────────────────────────────

(declaim (inline al-i32-wrap))
(defun al-i32-wrap (n)
  "32 位有符号回绕。"
  (let ((u (ldb (byte 32 0) n)))
    (if (>= u #x80000000) (- u #x100000000) u)))

(defun al-num2 (a b)
  "统一数值类型：任一浮点 → double-float 对。"
  (if (or (floatp a) (floatp b))
      (values (float a 1d0) (float b 1d0) t)
      (values a b nil)))

;;; ── 算术 ─────────────────────────────────────────────────────────────────────

(defsubr "+" (args)
  (let ((acc (if args 0 0)))
    (declare (type integer acc))
    (dolist (a args)
      (cond
        ((floatp a) (setf acc (float a 1d0)) (return (reduce #'+ (cons acc args))))
        (t (incf acc a))))
    (if (floatp acc) acc (al-i32-wrap acc))))

(defsubr "-" (args)
  (cond
    ((null args) 0)
    ((null (cdr args)) (let ((a (car args)))
                         (if (floatp a) (- a) (al-i32-wrap (- a)))))
    (t (let ((acc (car args)))
         (dolist (a (cdr args))
           (if (and (not (floatp acc)) (floatp a))
               (return (reduce #'- (cons (float acc 1d0) (cdr args))))
               (setf acc (- acc a))))
         (if (floatp acc) acc (al-i32-wrap acc))))))

(defsubr "*" (args)
  (let ((acc 1))
    (dolist (a args)
      (if (floatp a)
          (return (reduce #'* (cons (float acc 1d0) args)))
          (setf acc (* acc a))))
    (if (floatp acc) acc (al-i32-wrap acc))))

(defun al-div (a b)
  "AutoLISP 除法：整数÷整数 → 整数（截断），含浮点 → 浮点。"
  (if (or (floatp a) (floatp b))
      (/ (float a 1d0) (float b 1d0))
      (if (zerop b) (error "Divide by zero") (truncate a b))))

(defsubr "/" (args)
  (cond
    ((null args) 0)
    ((null (cdr args)) (let ((a (car args))) (al-div 1 a)))
    (t (let ((acc (car args)))
         (dolist (a (cdr args)) (setf acc (al-div acc a)))
         acc))))

(defsubr "1+" (args) (let ((a (car args)))
                     (if (floatp a) (+ a 1.0d0) (al-i32-wrap (1+ a)))))
(defsubr "1-" (args) (let ((a (car args)))
                     (if (floatp a) (- a 1.0d0) (al-i32-wrap (1- a)))))

(defsubr "rem" (args) (destructuring-bind (a b) args
                       (if (or (floatp a) (floatp b)) (rem a b) (al-i32-wrap (rem a b)))))
(defsubr "abs" (args) (let ((a (first args))) (if (floatp a) (abs a) (al-i32-wrap (abs a)))))
(defsubr "max" (args) (reduce #'max args))
(defsubr "min" (args) (reduce #'min args))
(defsubr "fix" (args) (floor (first args)))
(defsubr "float" (args) (float (first args) 1d0))

(defun al-bitop (op args)
  (al-i32-wrap (reduce op (mapcar (lambda (x) (floor x)) args))))

(defsubr "logand" (args) (al-bitop #'logand args))
(defsubr "logior" (args) (al-bitop #'logior args))
(defsubr "logxor" (args) (al-bitop #'logxor args))
(defun al-lsh (val n) (if (>= n 0) (al-i32-wrap (ash val n)) (al-i32-wrap (ash val n))))
(defsubr "lsh" (args) (apply #'al-lsh args))

;;; ── 比较 ─────────────────────────────────────────────────────────────────────

(defun al-rel (op rlist first)
  "变参比较 op：要求所有相邻对满足 op 才返回 T。first 表示单参时（比较数与0？AutoLISP：单参取 T）。"
  (if (< (length rlist) 2) t
      (every (lambda (a b)
               (if (and (numberp a) (numberp b))
                   (if (or (floatp a) (floatp b))
                       (funcall op (float a 1d0) (float b 1d0))
                       (funcall op a b))
                   (and (stringp a) (stringp b)
                        (funcall op a b))))
             rlist (cdr rlist))))

(defsubr "=" (args)
  (or (null args)
      (every (lambda (a b) (al-eq-num a b)) args (cdr args))))
(defsubr "/=" (args)
  (and args
       (every (lambda (a b) (not (al-eq-num a b))) args (cdr args))))
(defsubr "<" (args) (al-rel #'< args nil))
(defsubr "<=" (args) (al-rel #'<= args nil))
(defsubr ">" (args) (al-rel #'> args nil))
(defsubr ">=" (args) (al-rel #'>= args nil))

(defun al-eq-num (a b)
  "= 的语义：两数相等（int/real 混合比较数值），两字符/串相等。"
  (cond
    ((and (numberp a) (numberp b)) (if (or (floatp a) (floatp b)) (= (float a 1d0) (float b 1d0)) (= a b)))
    ((and (stringp a) (stringp b)) (string= a b))
    ((and a b (symbolp a) (symbolp b)) t)
    (t (eql a b))))

;;; ── 谓词 ─────────────────────────────────────────────────────────────────────

(defsubr "atom" (args) (not (al-cons-p (first args))))
(defsubr "null" (args) (null (first args)))
(defsubr "listp" (args) (al-list-p (first args)))
(defsubr "consp" (args) (al-cons-p (first args)))
(defsubr "numberp" (args) (numberp (first args)))
(defsubr "integerp" (args) (integerp (first args)))
(defsubr "realp" (args) (floatp (first args)))
(defsubr "zerop" (args) (and (numberp (first args)) (zerop (first args))))
(defsubr "minusp" (args) (and (numberp (first args)) (minusp (first args))))
(defsubr "boundp" (args) (if (and (first args) (symbolp (first args)))
                             (nth-value 1 (gethash (first args) *dyn-bindings*))
                             nil))

(defun al-type-of (x)
  (al-int nil))
(defsubr "type" (args)
  (let ((x (first args)))
    (cond ((null x) (al-int "NIL"))
          ((eq x t) (al-int "T"))
          ((integerp x) (al-int "INT"))
          ((floatp x) (al-int "REAL"))
          ((stringp x) (al-int "STR"))
          ((symbolp x) (al-int "SYM"))
          ((file-obj-p x) (al-int "FILE"))
          ((fn-p x) (al-int "FUN"))
          ((subr-p x) (al-int "SUBR"))
          ((cad-stub-p x) (al-int (string-upcase (string (cad-stub-kind x)))))
          ((al-cons-p x) (al-int "LIST"))
          (t (al-int "UNKNOWN")))))

;;; ── cons 与列表 ───────────────────────────────────────────────────────────────

(defsubr "cons" (args) (destructuring-bind (a b) args (cons a b)))
(defsubr "car" (args) (let ((l (first args))) (if (al-cons-p l) (car l) nil)))
(defsubr "cdr" (args) (let ((l (first args))) (if (al-cons-p l) (cdr l) nil)))

(defmacro def-car-cdr (name ops)
  "生成 caar/cadr/cdr 族。ops 为字符列表：A=car C=cdr。"
  `(defsubr ,name (args)
     (let ((l (first args)))
       ,(reduce (lambda (acc op)
                  (if (char= op #\A) `(if (al-cons-p ,acc) (car ,acc) nil)
                      `(if (al-cons-p ,acc) (cdr ,acc) nil)))
                (reverse ops)
                :initial-value 'l))))

(def-car-cdr "caar" "AA")
(def-car-cdr "cadr" "DA")
(def-car-cdr "cdar" "AD")
(def-car-cdr "cddr" "DD")
(def-car-cdr "caaar" "AAA")
(def-car-cdr "caadr" "DAA")
(def-car-cdr "cadar" "ADA")
(def-car-cdr "caddr" "DDA")
(def-car-cdr "cdaar" "AAD")
(def-car-cdr "cdadr" "DAD")
(def-car-cdr "cddar" "ADD")
(def-car-cdr "cdddr" "DDD")

(defsubr "list" (args) (copy-list args))
(defsubr "length" (args) (let ((l (first args)))
                          (if (al-cons-p l) (loop for x in l count t) 0)))
(defsubr "nth" (args) (destructuring-bind (n l) args (if (and (integerp n) (al-cons-p l) (>= n 0) (< n (length l))) (nth n l) nil)))
(defsubr "last" (args) (car (last (first args))))
(defsubr "member" (args)
  (let ((x (first args)) (l (second args)))
    (member x l :test #'al-eq-num)))
(defsubr "assoc" (args)
  (let ((key (first args)) (alist (second args)))
    (assoc key alist :test #'al-eq-num)))
(defsubr "append" (args)
  (let ((res (car (last args))))
    (declare (ignore res))
    (reduce #'append (remove nil args) :initial-value nil)))
(defsubr "reverse" (args) (reverse (first args)))
(defsubr "subst" (args) (destructuring-bind (new old lst) args (subst new old lst :test #'equal)))
(defsubr "vl-remove" (args) (destructuring-bind (x l) args (remove x l :test #'equal)))

;;; ── 字符串 ──────────────────────────

(defsubr "strcat" (args) (apply #'concatenate 'string args))
(defsubr "strlen" (args) (if (stringp (first args)) (length (first args)) 0))
(defsubr "substr" (args)
  (let ((s (first args)) (start (second args)) (len (third args)))
    (let ((n (length s)))
      (setf start (if (and (integerp start) (plusp start)) start 1))
      (when (> start n) "")
      (let ((beg (1- start)))
        (if (and len (integerp len) (<= (+ beg len) n))
            (subseq s beg (+ beg len))
            (subseq s beg))))))

(defsubr "strcase" (args)
  (let ((s (first args)) (up (second args)))
    (if up (string-upcase s) (string-downcase s))))

(defun al-trim (s)
  (string-trim '(#\Space #\Tab #\Return #\Newline) s))

(defsubr "strtrim" (args) (al-trim (first args)))
(defsubr "strleft" (args) (destructuring-bind (s n) args
                            (let ((m (min n (length s)))) (subseq s 0 m))))
(defsubr "strright" (args) (destructuring-bind (s n) args
                             (let ((m (min n (length s)))) (subseq s (- (length s) m)))))

(defsubr "atoi" (args) (or (ignore-errors (parse-integer (al-trim (first args)) :junk-allowed t)) 0))
(defsubr "atof" (args)
  (or (ignore-errors (coerce (read-from-string (al-trim (first args))) 'double-float)) 0.0d0))
(defsubr "itoa" (args) (princ-to-string (first args)))
(defsubr "ascii" (args) (if (stringp (first args)) (char-code (char (first args) 0)) 0))
(defsubr "chr" (args) (string (code-char (first args))))

;;; ── 输入输出 ─────────────────────────────────────────────────────────────────

(defsubr "princ" (args) (let ((x (and args (first args)))) (al-print x) x))
(defsubr "print" (args) (let ((x (and args (first args)))) (al-print x) x))
(defsubr "prin1" (args) (let ((x (and args (first args)))) (write x :escape t) x))
(defsubr "terpri" (args) (terpri) nil)
(defsubr "princ-to-string" (args) (al-to-string (first args)))
(defsubr "prin1-to-string" (args) (prin1-to-string (first args)))
(defsubr "prompt" (args) (let ((s (first args))) (princ s) s))

;;; ── 函数应用 ─────────────────────────────────────────────────────────────────

(defsubr "apply" (args)
  (let ((f (first args)) (lst (second args)))
    (al-call (al-as-function f) lst)))

(defsubr "funcall" (args)
  (al-call (al-as-function (first args)) (rest args)))

(defsubr "mapcar" (args)
  (let ((f (al-as-function (first args)))
        (lists (rest args)))
    (when lists
      (let ((n (apply #'min (mapcar (lambda (l) (if (al-cons-p l) (length l) 0))
                                    lists))))
        (loop for i below n
              collect (al-call f (mapcar (lambda (l) (nth i l)) lists)))))))

(defsubr "eval" (args) (al-eval-form (first args)))

;;; ── 其它 ─────────────────────────────────────────────────────────────────────

(defsubr "eq" (args) (eq (first args) (second args)))
(defsubr "equal" (args) (equal (first args) (second args)))
(defsubr "not" (args) (null (first args)))

;;; ── 几何（点 = (x y [z]) 列表）──────────────────────────────────────────────

(defun al-point-coords (p)
  "AutoLISP 点 (x y [z]) → 坐标列表（缺省 z=0）。"
  (list (float (or (car p) 0) 1d0)
        (float (or (cadr p) 0) 1d0)
        (float (or (caddr p) 0) 1d0)))

(defsubr "distance" (args)
  (destructuring-bind (p1 p2) args
    (let ((a (al-point-coords p1))
          (b (al-point-coords p2)))
      (sqrt (+ (expt (- (first a) (first b)) 2)
               (expt (- (second a) (second b)) 2)
               (expt (- (third a) (third b)) 2))))))

(defsubr "angle" (args)
  (destructuring-bind (p1 p2) args
    (let ((a (al-point-coords p1))
          (b (al-point-coords p2)))
      (atan (- (second b) (second a))
            (- (first b) (first a))))))

(defsubr "polar" (args)
  (destructuring-bind (p ang dist) args
    (let ((a (al-point-coords p)))
      (list (+ (first a) (* (float dist 1d0) (cos (float ang 1d0))))
            (+ (second a) (* (float dist 1d0) (sin (float ang 1d0))))))))

(defun register-core-builtins ()
  "当前已用 defsubr 自动注册；此函数仅作文档/兼容入口。"
  t)
