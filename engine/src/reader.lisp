;;;; reader.lisp — AutoLISP 读入器
;;;;
;;;; 独立于 CL readtable 的字符级 tokenizer + parser，与 compiler/lexer.py 对齐：
;;;;   * 注释：`;` 行注释、`;| ... |;` 块注释
;;;;   * 字符串转义：\n \r \t \e \ \" （其余 `\x` 原样保留）
;;;;   * `1+`/`1-` 作为符号（非数字）
;;;;   * 整数/实数（含 1.5e-3 指数）；dotted pair `(a . b)`
;;;;   * `'` → (QUOTE ...)、`#'` → (FUNCTION ...)
;;;;   * 符号统一大写（大小写不敏感）
;;;; 整数字面量超出 32 位有符号范围时按 fix 文档语义转为实数。
(in-package #:atlisp)

(defparameter *int32-min* -2147483648)
(defparameter *int32-max* 2147483647)

(defun delim-p (ch)
  (and ch (member ch '(#\Space #\Tab #\Return #\Newline #\( #\) #\' #\" #\;))))

(defstruct (tok (:constructor tok (kind value)))
  kind     ; :lparen :rparen :quote :fquote :dot :num :str :sym :eof
  value)

;;; ── tokenizer ─────────────────────────────────────────────────────────────

(defun skip-comments (s pos)
  "跳过空白与注释，返回新 pos。"
  (loop
    (when (>= pos (length s)) (return pos))
    (let ((ch (char s pos)))
      (cond
        ((member ch '(#\Space #\Tab #\Return)) (incf pos))
        ((char= ch #\Newline) (incf pos))
        ((char= ch #\;)
         (cond
           ((and (> (length s) (1+ pos)) (char= (char s (1+ pos)) #\|))
            (let ((end (search "|;" s :start2 (+ pos 2))))
              (if end (setf pos (+ end 2)) (setf pos (length s)))))
           (t
            (let ((end (position #\Newline s :start pos)))
              (if end (setf pos end) (setf pos (length s)))))))
        (t (return pos))))))

(defun read-string (s pos)
  "读取字符串 token（pos 已在开引号后），处理转义。返回 (str . newpos)。"
  (let ((n (length s))
        (out (make-string-output-stream)))
    (loop
      (when (>= pos n) (error "Unterminated string"))
      (let ((ch (char s pos)))
        (cond
          ((char= ch #\\)
           (incf pos)
           (if (>= pos n) (error "Unterminated string escape"))
           (let ((e (char s pos)))
             (case e
               (#\n (write-char #\Newline out))
               (#\r (write-char #\Return out))
               (#\t (write-char #\Tab out))
               (#\e (write-char (code-char 27) out))
               (otherwise (write-char e out)))
             (incf pos)))
          ((char= ch #\")
           (return (values (get-output-stream-string out) (1+ pos))))
          (t (write-char ch out) (incf pos)))))))

(defun scan-token (s pos)
  "扫描一个符号/数字 token（到分隔符为止，`.` 留在 token 内）。返回 (token . newpos)。"
  (let ((start pos)
        (n (length s)))
    (loop while (and (< pos n) (not (delim-p (char s pos)))) do (incf pos))
    (values (subseq s start pos) pos)))

(defun integer-token-p (str)
  "整数：-?\d+"
  (let ((len (length str)))
    (when (plusp len)
      (let ((i (if (find (char str 0) "-+") 1 0)))
        (and (< i len)
             (loop for k from i below len always (digit-char-p (char str k))))))))

(defun real-token-p (str)
  "实数：-?\d+\.\d+([eE][+-]?\d+)? （要求小数点后有数字）"
  (let* ((len (length str))
         (i (if (and (plusp len) (find (char str 0) "-+")) 1 0)))
    (when (< i len)
      (let ((dot (position #\. str :start i)))
        (and dot
             (> dot i)
             (< (1+ dot) len)
             (digit-char-p (char str (1+ dot)))
             (let ((tail (subseq str (1+ dot))))
               (if (every #'digit-char-p tail)
                   t
                   (let ((digits (position-if (lambda (c) (find c "eE")) tail)))
                     (and digits
                          (every #'digit-char-p (subseq tail 0 digits))
                          (let* ((exp (subseq tail (1+ digits)))
                                 (r (if (and (plusp (length exp)) (find (char exp 0) "+-"))
                                        (subseq exp 1) exp)))
                            (and (plusp (length r)) (every #'digit-char-p r))))))))))))

(defun al-parse-real (str)
  (coerce (read-from-string str) 'double-float))

(defun tokenize (source)
  "把源码切成 token 列表（尾部 :eof）。"
  (let ((tokens '())
        (pos 0))
    (loop
      (setf pos (skip-comments source pos))
      (when (>= pos (length source))
        (return (nreverse (cons (tok :eof nil) tokens))))
      (let ((ch (char source pos)))
        (cond
          ((char= ch #\() (push (tok :lparen nil) tokens) (incf pos))
          ((char= ch #\)) (push (tok :rparen nil) tokens) (incf pos))
          ((and (char= ch #\#) (< (1+ pos) (length source)) (char= (char source (1+ pos)) #\'))
           (push (tok :fquote nil) tokens) (incf pos 2))
          ((char= ch #\') (push (tok :quote nil) tokens) (incf pos))
          ((char= ch #\")
           (multiple-value-bind (str newpos) (read-string source (1+ pos))
             (push (tok :str str) tokens)
             (setf pos newpos)))
          (t
           (multiple-value-bind (tok-str newpos) (scan-token source pos)
             (cond
               ((string= tok-str ".") (push (tok :dot nil) tokens))
               ((integer-token-p tok-str)
                (push (tok :num (al-coerce-int (parse-integer tok-str))) tokens))
               ((real-token-p tok-str)
                (push (tok :num (al-parse-real tok-str)) tokens))
               (t (push (tok :sym (al-int tok-str)) tokens)))
             (setf pos newpos))))))))

(defun al-coerce-int (n)
  "整数字面量超出 32 位有符号范围 → 截断实数（fix 文档语义）。"
  (if (or (< n *int32-min*) (> n *int32-max*))
      (coerce n 'double-float)
      n))

;;; ── parser ────────────────────────────────────────────────────────────────

(defun parse-forms (p)
  "读取全部顶层形式，返回列表。"
  (loop
    (let ((tk (tok-kind (pf-peek p))))
      (when (eq tk :eof) (return (nreverse *al-acc*)))
      (push (parse-form p) *al-acc*))))

(defstruct (pf (:constructor make-pf (tokens)))
  (tokens nil)
  (idx 0))

(defun pf-peek (p) (aref (pf-tokens p) (pf-idx p)))
(defun pf-next (p) (prog1 (aref (pf-tokens p) (pf-idx p)) (incf (pf-idx p))))

(defvar *al-acc* nil)

(defun parse-form (p)
  "解析一个datum。"
  (let* ((tk (pf-next p))
         (kind (tok-kind tk)))
    (case kind
      (:quote (list (al-int "QUOTE") (parse-form p)))
      (:fquote (list (al-int "FUNCTION") (parse-form p)))
      (:num (tok-value tk))
      (:str (tok-value tk))
      (:sym (tok-value tk))
      (:lparen (parse-list p))
      (:rparen (error "Unexpected ')'"))
      (:eof (error "Unexpected end of input"))
      (otherwise (error "Bad token: ~a" tk)))))

(defun parse-list (p)
  "解析 `(...)` 表，支持 dotted pair。"
  (let (elems)
    (loop
      (let ((kind (tok-kind (pf-peek p))))
        (case kind
          (:rparen
           (pf-next p)
           (return (nreverse elems)))
          (:eof (error "Unbalanced parentheses"))
          (:dot
           (pf-next p)
           (when (null elems) (error "Dotted pair with no car"))
           (let ((tail (parse-form p)))
             (when (not (eq (tok-kind (pf-peek p)) :rparen))
               (error "Dotted pair must be last"))
             (pf-next p)
             (return
               (let ((lst (nreverse elems)))
                 (rplacd (last lst) tail)
                 lst))))
          (t (push (parse-form p) elems)))))))

(defun al-read-source (source)
  "解析整个源码字符串，返回顶层形式列表。"
  (let ((*al-acc* nil))
    (parse-forms (make-pf (coerce (tokenize source) 'vector)))))

(defun al-read-one (source)
  "解析第一个形式（REPL 用）。返回 (values form ok?)。"
  (let ((*al-acc* nil))
    (handler-case
        (values (parse-form (make-pf (coerce (tokenize source) 'vector))) t)
      (error () (values nil nil)))))
