;;;; main.lisp — CLI 入口（atlisp run <file>；atlisp repl；atlisp eval <src>）
(in-package #:atlisp)

(defvar *load-exit-code* 0)

(defun al-run-file (path)
  "加载并顺序执行 AutoLISP 文件，返回最后一个顶层形式的值。"
  (let ((last nil))
    (with-open-file (s path :direction :input :external-format :utf-8)
      (let ((content (make-string (file-length s))))
        (read-sequence content s)
        (dolist (f (al-read-source content) last)
          (setf last (al-eval-form f)))))))

(defun al-repl ()
  "简单 REPL。"
  (format t "~&; atlisp engine ~a (SBCL)~%; Q 退出, (princ ...) 打印~%" "0.1")
  (loop
    (format t "~&#> ")
    (finish-output)
    (handler-case
        (let ((line (read-line nil nil :eof)))
          (when (eq line :eof) (return))
          (when (string= (string-trim " " line) "") (return))
          (let ((forms (al-read-source line)))
            (dolist (f forms)
              (handler-case (progn (let ((v (al-eval-form f)))
                                     (al-print v) (terpri)))
                (error (e) (format t "~&! ~a~%" e))))))
      (error (e) (format t "~&! ~a~%" e)))))

(defun al-message (format-string &rest args)
  (apply #'format *standard-output* format-string args))

(defun finalize-exit-code (code)
  (setf *load-exit-code* code))

;;; 直接作为可执行文件：sb-ext:save-lisp-and-die :toplevel
(defun engine-main ()
  (let ((args (uiop:command-line-arguments)))
    (cond
      ((null args) (al-repl))
      ((string= (car args) "run")
       (if (null (cdr args))
           (progn (format *error-output* "~&usage: atlisp run <file.lsp>~%")
                  (finalize-exit-code 2))
           (let ((path (second args)))
             (if (probe-file path)
                 (handler-case
                     (let ((v (al-run-file path)))
                       ;; 仅在最后一次形式有「可打印非 nil 值」且显式 princ 时打印；
                       ;; run 默认静默，用户用 (princ ...) 控制输出
                       v)
                   (error (e) (format *error-output* "~&error: ~a~%" e)
                          (finalize-exit-code 1)))
                 (progn (format *error-output* "~&error: cannot open ~a~%" path)
                        (finalize-exit-code 1))))))
      ((string= (car args) "eval")
       (let ((v (al-eval-source (second args))))
         (al-print v) (terpri)))
      ((string= (car args) "repl") (al-repl))
      (t
       (format *error-output* "~&usage: atlisp {run <file> | eval <src> | repl}~%")
       (finalize-exit-code 2)))))
