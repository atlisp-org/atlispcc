;; ── compat/cl-functions.lsp ──────────────────────────────────────────
;; @provides compat-cl-functions
;; 在 AutoLISP 环境中兼容 Common Lisp 函数名和语义
#-sbcl
(progn
  (vl-load-com)
  (if (null vlax-ename->vla-object)
    (progn
      (@::alert "Not found Visual LISP environment. Please install a VLISP-compatible CAD.")
      (princ "\n;; @lisp Error: No Visual LISP environment found.\n")
      nil))
  (set 'directory vl-directory-files)
  (set 'delete-file vl-file-delete)
  (set 's2l vl-string->list)
  (set 'l2s vl-list->string)
  (set 'e2o vlax-ename->vla-object)
  (set 'o2e vlax-vla-object->ename)
  (set 'make-object vlax-get-or-create-object)
  (set 'remove vl-remove)
  (set 'remove-if vl-remove-if)
  (set 'remove-if-not vl-remove-if-not)
  (set 'remove-duplicates @::remove-duplicates)
  (set 'prin1-to-string vl-prin1-to-string)
  (set 'princ-to-string vl-princ-to-string)
  (set 'every vl-every)
  (set 'some vl-some)
  (set 'sort vl-sort)
  (set 'truncate fix)
  (set 'string/= /=)
  (set '@::string/= /=)
  (set 'cl::string/= /=)
  (set 'string-trim vl-string-trim)
  (set 'string-left-trim vl-string-left-trim)
  (set 'string-right-trim vl-string-right-trim)
  (set 'string-concat strcat)
  (set 'substitute subst)
  (set 'mismatch vl-string-mismatch)
  (set 'search vl-string-search)
  (defun cl::stringp (sym)
    "判断一个符号是否为字符串类型"
    (= "STR" (vl-princ-to-string (type sym))))
  (set 'stringp cl::stringp)
  (defun cl::count (ele lst)
    "统计一个元素在列表或字符串中出现的次数"
    (if (cl::stringp lst)
      (progn
        (setq lst (vl-string->list lst))
        (if (cl::stringp ele)
          (setq ele (ascii ele)))))
    (-
      (length lst)
      (length (remove ele lst))))
  (set 'count cl::count)
  (defun cl::count-if (fun lst)
    "统计满足条件的元素在列表中出现的次数"
    (-
      (length lst)
      (length (remove-if fun lst))))
  (set 'count-if cl::count-if)
  (defun cl::count-if-not (fun lst)
    "统计不满足条件的元素在列表中出现的次数"
    (-
      (length lst)
      (length (remove-if-not fun lst))))
  (set 'count-if-not cl::count-if-not)
  (defun cl::find (ele lst / len original)
    "返回元素在列表或字符串中的位置，如果不存在则返回nil"
    (setq len      (length lst)
          original lst)
    (while (and lst (not (eq ele (car lst))))
      (setq lst (cdr lst)))
    (if lst
      (- len (length lst))
      nil))
  (set 'find cl::find)
  (defun cl::position (ele seq / lst)
    "返回元素在列表或字符串中的位置，如果不存在则返回nil"
    (if (cl::stringp seq)
      (progn
        (setq lst (vl-string->list seq)
              seq lst)
        (if (cl::stringp ele)
          (setq ele (ascii ele)))))
    (vl-position ele seq))
  (set 'position cl::position)
  (setq :use =)
  (setq :export =)
  (defun cl::elt (lst n)
    "element"
    (nth n lst))
  (set 'elt cl::elt)
  (defun cl::evenp (n)
    "测试一个整数是否为偶数"
    (=
      0
      (rem
        (fix n)
        2)))
  (set 'evenp cl::evenp)
  (defun cl::type-of (x)
    "返回一个对象的类型"
    (cond
      ((listp x)
       (cond
         ((and
            (or
              (= 2 (length x))
              (= 3 (length x)))
            (apply 'and (mapcar 'numberp x)))
          'point)
         (t 'LIST)))
      (t (type x))))
  (set 'type-of cl::type-of)

  (defun cl::string-equal (str1 str2)
    "比较两个字符串是否相等，忽略大小写"
    (if
      (and
        (eq 'str (type str1))
        (eq 'str (type str2)))
      (= (strcase str1) (strcase str2))))
  (set 'string-equal cl::string-equal)
  (setq :@ ':@)
  (defun cl::string-downcase (str)
    "将字符串转换为小写"
    (strcase str t))
  (set 'string-downcase cl::string-downcase)
  (defun cl::string-upcase (str)
    "将字符串转换为大写"
    (strcase str))
  (set 'string-upcase cl::string-upcase)
  (defun cl::read-from-string (str / form)
    "从字符串中读取一个表达式"
    (setq form (read str))
    (@::handle-keywords form)
    form)
  (set 'read-from-string cl::read-from-string)
  (defun @::eval (form)
    "在当前环境中安全执行表达式，返回结果或错误对象（需用 vl-catch-all-error-p 检查）"
    "any"
    "(@::eval '(+ 1 2))"
    (@::handle-keywords form)
    (vl-catch-all-apply '@::safe-eval (list form)))
  (defun cl::defpackage (name use export)
    "定义一个包"
    (list name use export))
  (set 'defpackage cl::defpackage)
  (defun cl::use-package (name)
    "使用一个包"
    (list name))
  (set 'use-package cl::use-package)
  (defun cl::defvar (var value doc)
    "本函数用于当前用过骗过编辑器对未定义变量的提示，不起其它做用，还是需要用setq 给变量赋值。"
    (atom doc)
    (set var value))
  (set 'defvar cl::defvar)
(defun cl::defconstant (name value doc)
  "定义全局常量。全局常量通常以 + 开始和结尾。逻辑意义上的。"
  ""
  "(defconstant '+aaa+ 2)"
  (atom doc)
  (setq name (vl-symbol-name name))
  (eval
    (list 'pragma
      (list 'quote (list (cons 'unprotect-assign name)))
    )
  )
  (set (read name) value)
  (eval	(list 'pragma
      (list 'quote (list (cons 'protect-assign name)))
    )
  )
)
  (set 'defconstant cl::defconstant)
  (defun cl::in-package (pkgname)
    "设置当前包"
    (setq *package* pkgname))
  (set 'in-package cl::in-package)
  (defun cl::floor (number)
    "向下取整"
    (if (>= number 0)
      (fix number)
      (if (< (- number (fix number)) 0)
        (fix (1- number))
        (fix number))))
  (set 'floor cl::floor)
  (defun cl::ceiling (number)
    "向上取整"
    (if
      (and
        (>= number 0)
        (> (- number (fix number)) 0))
      (fix (1+ number))
      (fix number)))
  (set 'ceiling cl::ceiling)
  (defun cl::round (number)
    "四舍五入"
    (if (>= number 0)
      (fix (+ number 0.5))
      (fix (- number 0.5))))
  (set 'round cl::round)
  (defun cl::mod (x y)
    "返回 x 除以 y 的余数"
    (cl::floor (- x (* y (fix (/ (float x) (float y)))))))
  (set 'mod cl::mod)
  (defun cl::probe-directory (path)
    "检查一个路径是否为目录"
    (and
      (findfile path)
      (vl-file-directory-p path)))
  (set 'probe-directory cl::probe-directory)
  (defun cl::probe-file (path)
    "检查一个路径是否为文件"
    (and
      (findfile path)
      (not (vl-file-directory-p path))))
  (set 'probe-file cl::probe-file)
  (defun cl::string::subst-dqm (str)
    "将字符串中的双引号替换为转义双引号"
    (@::string-subst "\\\"" "\"" str))
  (set 'string::subst-dqm cl::string::subst-dqm)
  (defun @::require (fun-match)
    "从云端加载函数定义"
    (@::load-module 'function)
    (if
      (or
        (eq 'subr (type fun::require))
        (eq 'usubr (type fun::require)))
      (fun::require fun-match)
      (princ (_ "load function module failure."))))
  (defun cl::symbol-function (sym)
    "返回符号的函数对象"
    (vl-catch-all-apply '@::safe-eval (list (list 'function sym))))
  (set 'symbol-function cl::symbol-function)
  (defun cl::nthcdr (n lst)
    "返回列表 lst 中从第 n 个元素开始的子列表"
    (if (< n 1) lst (cl::nthcdr (1- n) (cdr lst))))
  (set 'nthcdr cl::nthcdr)
  (defun cl::butlast (lst / len)
    "返回列表 lst 中除最后一个元素外的所有元素"
    (setq len (length lst))
    (if (> len 1)
      (reverse (cdr (reverse lst)))
      nil))
  (set 'butlast cl::butlast)
  (defun cl::subseq (seq start end / result)
    "返回序列 seq 中从 start 到 end 的子序列"
    (if (= (type seq) 'STR)
      (progn
        (if (null end) (setq end (strlen seq)))
        (substr seq (1+ start) (- end start)))
      (progn
        (if (null end) (setq end (length seq)))
        (setq seq (cl::nthcdr start seq))
        (setq result nil)
        (repeat (- end start)
          (setq result (cons (car seq) result)
                seq    (cdr seq)))
        (reverse result))))
  (set 'subseq cl::subseq))

;; ── compat/cl-macros.lsp ──────────────────────────────────────────
;; @depends compat-cl-functions
;; @provides compat-cl-macros
;; 在 AutoLISP 环境中兼容 Common Lisp 函数名和语义
#-sbcl
(progn
  ;;; ============ Macro System ============
  (setq @::*macro-table* (list))

  (defun @::get-macro (name)
    "获取宏定义"
    (cdr (assoc name @::*macro-table*)))

  (defun @::set-macro (name body)
    "设置宏定义"
    (setq @::*macro-table* (cons (cons name body) @::*macro-table*)))

  (defun @::macro-subst (form args / result item)
    "将宏调用 form 中的参数替换为 args"
    (setq result nil)
    (while form
      (setq item (car form))
      (cond
        ((and args (numberp item) (> item 0))
         (setq result (cons (nth (1- item) args) result)))
        ((listp item)
         (setq result (cons (@::macro-subst item args) result)))
        (t
         (setq result (cons item result))))
      (setq form (cdr form)))
    (reverse result))

  (defun @::expand-let (form / bindings body vars vals)
    "将 let 表达式 form 展开为 lambda 表达式"
    (setq bindings (cadr form)
          body     (cddr form)
          vars     (mapcar 'car bindings)
          vals     (mapcar 'cadr bindings))
    (cons (list 'lambda vars (cons 'progn body)) vals))

  (defun @::expand-dolist (form / var lst result body)
    "将 dolist 表达式 form 展开为 foreach 表达式"
    (setq var    (caadr form)
          lst    (cadadr form)
          result (caddr (cadr form))
          body   (cddr form))
    (list
      'catch
      ''return
      (cons
        'foreach
        (cons
          var
          (cons lst body)))
      result))

  (defun @::macro-expand (form / m)
    "展开宏调用 form"
    (if (listp form)
      (cond
        ((eq 'let (car form))
         (@::expand-let form))
        ((eq 'dolist (car form))
         (@::expand-dolist form))
        (t
         (setq m (@::get-macro (car form)))
         (if m (@::macro-subst m (cdr form)) form)))
      form))

  (defun defmacro (name body)
    "定义一个宏"
    (@::set-macro name body)
    (princ (strcat "Macro: " (vl-symbol-name name) "\n"))
    name))


;; ── platform-api.lsp ──────────────────────────────────────────
;; @provides platform-api
(vl-load-com)
;;(in-package :@)
;;(use-package :autolisp)

;; Self-contained platform abstraction layer
;; Only uses basic AutoLISP + base-function.lsp primitives

(defun @::platform-is-linux-p ()
  (or
    (and (getvar "platform")
         (wcmatch (strcase (getvar "platform")) "*LINUX*"))
    (and (getenv "HOME")
         (not (getenv "WINDIR")))))
(setq @::*platform-cache* (if (@::platform-is-linux-p) 'linux 'windows))
(defun @::platform-is-windows-p () (not (@::platform-is-linux-p)))

(defun @::platform-path (str)
  (if (@::platform-is-linux-p)
      (while (vl-string-search "\\" str)
        (setq str (vl-string-subst "/" "\\" str)))
      (while (vl-string-search "/" str)
        (setq str (vl-string-subst "\\" "/" str))))
  str)

(defun @::platform-temp-path (name)
  (if (@::platform-is-linux-p)
      (strcat @::*tmp-path* name ".dcl")
      (vl-filename-mktemp name @::*tmp-path* ".dcl")))

(defun @::platform-registry-write (key value)
  (if (not (@::platform-is-linux-p))
      (vl-registry-write "HKEY_CURRENT_USER\\Software\\atlisp.cn" key value)))

(defun @::platform-registry-read (key)
  (if (@::platform-is-linux-p)
      nil
      (vl-registry-read "HKEY_CURRENT_USER\\Software\\atlisp.cn" key)))

(defun @::platform-machineid ()
  (cond
   ((@::platform-is-linux-p)
    (if (findfile (strcat @::*prefix-config* "@lisp.id"))
        (vl-string-right-trim
         "\n"
         (@::get-file-contents (findfile (strcat @::*prefix-config* "@lisp.id"))))))
   (t
    (@::platform-registry-read "MachineId"))))

(defun @::platform-machineid-save (mid / fp)
  (if (not (@::platform-is-linux-p))
      (@::platform-registry-write "MachineId" mid))
  (if (and @::*prefix-config*
           (findfile (vl-filename-directory @::*prefix-config*))
           (null (findfile (strcat @::*prefix-config* "@lisp.id"))))
      (progn
        (setq fp (vl-catch-all-apply 'open (list (strcat @::*prefix-config* "@lisp.id") "w")))
        (if (not (vl-catch-all-error-p fp))
            (progn
              (write-line mid fp)
              (close fp))))))

(defun @::platform-http-winhttp (method uri post-data content-type / req result)
  "WinHTTP 统一请求辅助函数。method: \"GET\" / \"POST\" / \"HEAD\", post-data/content-type 为 nil 时不做 POST。返回 (response-text . http-status) 或 nil。"
  (setq req (@::http-pool-acquire))
  (if (null req) (setq req (vlax-create-object @::*winhttp-progid*)))
  (if req
    (if (not (vl-catch-all-error-p
              (setq result (vl-catch-all-apply
                            (function (lambda ()
                               (vlax-invoke req 'OPEN method uri :vlax-false)
                               (if (= "POST" method)
                                 (@::set-headers req content-type (itoa (strbytelen post-data)))
                                 (@::set-headers req nil nil))
                               (if (= "POST" method)
                                 (vlax-invoke req 'Send post-data)
                                 (vlax-invoke req 'Send))
                               (vlax-invoke req 'WaitForResponse @::*waitforresponse*)
                               (list (vlax-get-property req 'ResponseText)
                                     (vlax-get-property req 'status))))))))
      (progn
        (@::http-pool-release req)
        (if (and result (= @::*http-status-ok* (cadr result)))
          (car result)))
      (progn
        (@::http-pool-release req)
        nil))
    nil))

(defun @::platform-http-post (uri data content-type / result)
  (if (boundp '@::wget)
    (cond
      ((@::platform-is-linux-p)
       (@::wget uri (strcat @::*tmp-path* (@::timestamp))
                (strcat " --header=\"Content-Type: " content-type "\""
                        " --header=\"Content-Length: " (itoa (strbytelen data)) "\""
                        " --post-data=\"" data "\""))
       (if (findfile (strcat @::*tmp-path* (@::timestamp)))
         (progn
           (setq result (@::get-file-contents (strcat @::*tmp-path* (@::timestamp))))
           (vl-file-delete (strcat @::*tmp-path* (@::timestamp)))
           result)))
      (t (@::platform-http-winhttp "POST" uri data content-type)))
    nil))

(defun @::platform-open-url (url)
  "安全地打开 URL。仅允许 http/https 协议，防止 shell 注入。"
  (if (and (eq 'str (type url))
           (wcmatch (strcase url) "HTTP://*,HTTPS://*"))
    (if (@::platform-is-linux-p)
      (command "shell" (strcat "xdg-open '" (vl-string-subst "'" "\\'" url) "'"))
      (startapp (strcat "explorer \"" (vl-string-subst "\"" "\\\"" url) "\"")))
    (princ "\n** @lisp: Invalid or blocked URL. Only http/https allowed. **\n")))

(defun @::platform-dispatch (linux-fn windows-fn)
  (if (@::platform-is-linux-p)
      (funcall linux-fn)
      (funcall windows-fn)))

(defun @::platform-http-get (uri / result)
  (if (boundp '@::wget)
      (cond
       ((@::platform-is-linux-p)
        (@::wget uri (strcat @::*tmp-path* (@::timestamp)) nil)
        (if (findfile (strcat @::*tmp-path* (@::timestamp)))
            (progn
              (setq result (@::get-file-contents (strcat @::*tmp-path* (@::timestamp))))
              (vl-file-delete (strcat @::*tmp-path* (@::timestamp)))
              result)))
       (t (@::platform-http-winhttp "GET" uri nil nil)))
      nil))

(defun @::platform-http-download (uri outfile / req result status body byte-list fp)
  (setq result nil)
  (setq req (@::http-pool-acquire))
  (if (null req)
    (setq req (vlax-create-object @::*winhttp-progid*)))
  (if (not (vl-catch-all-error-p
            (setq status (vl-catch-all-apply
                          (function (lambda ()
                             (vlax-invoke req 'OPEN "GET" uri :vlax-false)
                             (@::set-headers req nil nil)
                            (vlax-invoke req 'Send)
                            (vlax-invoke req 'WaitForResponse @::*waitforresponse*)
                            (vlax-get-property req 'status))) nil))))
      (progn
        (if (= @::*http-status-ok* status)
            (progn
              (setq body (vlax-get-property req 'ResponseBody))
              (setq byte-list (vlax-safearray->list (vlax-variant-value body)))
              (setq fp (vl-catch-all-apply 'open (list outfile "w")))
              (if (not (vl-catch-all-error-p fp))
                  (progn
                    (foreach b byte-list (write-char b fp))
                    (close fp)
                    (setq result outfile)))))))
  (@::http-pool-release req)
  result)

(defun @::platform-http-head (uri / result timestamp loopn)
  (if (boundp '@::wget)
      (cond
       ((@::platform-is-linux-p)
        (setq timestamp (@::timestamp))
        (@::wget uri (strcat @::*tmp-path* timestamp) nil)
        (setq loopn 0)
        (while (and (null (findfile (strcat @::*tmp-path* timestamp)))
                    (< loopn @::*max-retries*))
          (setq loopn (1+ loopn))
          (sleep 0.5))
        (if (findfile (strcat @::*tmp-path* timestamp))
            (progn (vl-file-delete (strcat @::*tmp-path* timestamp)) t)
            nil))
       (t (not (null (@::platform-http-winhttp "HEAD" uri nil nil)))))
      nil))

(defun @::cad-file-ext ()
  (if (boundp '@::*fasext*) @::*fasext* ".fas"))

(defun @::cad-is-zwcad ()
  (and (boundp 'is-zwcad) is-zwcad))

(defun @::cad-is-gcad ()
  (and (boundp 'is-gcad) is-gcad))

(defun @::cad-is-bricscad ()
  (and (boundp 'is-bricscad) is-bricscad))

(defun @::cad-is-autocad ()
  (and (boundp 'is-autocad) is-autocad))

T


;; ── lib/string-utils.lsp ──────────────────────────────────────────
;; @provides string-utils
;; -*- coding: utf-8 -*-
;; String utilities extracted from base-function.lsp
;; Development source — concatenated into base-function.lsp at build time
(defun @::max-char (str / maxc c)
  (setq maxc 0)
  (foreach c (vl-string->list str)
    (if (> c maxc) (setq maxc c)))
  maxc)
(defun @::dec2hex (n / chars)
  (setq chars (vl-string->list "0123456789ABCDEF"))
  (if (< n 16)
    (chr (nth n chars))
    (strcat (@::dec2hex (fix (/ n 16))) (chr (nth (rem n 16) chars)))))
(defun @::urlencode-local (str / res-lst prefix code)
  (if (null str) (setq str ""))
  (setq prefix (ascii "%"))
  (setq code '(48 49 50 51 52 53 54 55 56 57 65 66 67 68 69 70))
  (setq res-lst nil)
  (foreach n (vl-string->list str)
    (cond
      ((> n 255)
        (setq res-lst (append
            (reverse
              (vl-string->list (strcat "%u" (@::dec2hex n))))
            res-lst)))
      ((or (> 256 n 127) (member n (vl-string->list " ;/?:&=+$,#")))
        (setq res-lst (cons prefix res-lst))
        (setq res-lst (cons (nth (fix (/ n 16)) code) res-lst))
        (setq res-lst (cons (nth (rem n 16) code) res-lst)))
      ((< n 128)
        (setq res-lst (cons n res-lst)))))
  (vl-list->string (reverse res-lst)))
(defun @::string-to-list (str separator / s2la)
  "字符串转成列表，拆分字符串，指定字符来分隔字符串。"
  "拆分后的列表"
  (defun s2la (str separator / pos)
    (if (setq pos (vl-string-search separator str))
      (cons (substr str 1 pos)
        (s2la(substr str (+ pos 1 (strlen separator)))
          separator))
      (list str)))
  (if (and (p:stringp separator)
      (p:stringp str))
    (if(= "" separator)
      (mapcar (function (lambda (x)
            (chr x)))
        (vl-string->list  str))
      (s2la str separator)
    )
    (progn
      (@:log "ERROR" "parameter is not a string")
      nil)
))

(setq string:to-list @::string-to-list)
(defun @::list-to-string (slist separator / result n buf)
  (setq buf nil)
  (foreach n slist
    (if buf
      (setq buf (cons separator buf)))
    (setq buf (cons (@::to-string n) buf)))
  (if buf
    (setq result (apply 'strcat (reverse buf)))
    (setq result ""))
  result)
(setq string:from-list @::list-to-string)
(defun @::to-string (para)
  (cond
    ((eq 'INT (type-of para)) (itoa para))
    ((eq 'REAL (type-of para)) (rtos para 2 @::*decimal-places*))
    ((eq 'STR (type-of para)) para)
    ((eq 'LIST (type-of para)) (@::list-to-string para ";"))
    ((eq 'SYM (type-of para)) (vl-symbol-name para))
    ((null para) "")
    (T "T")))
(defun @::to-type (str typep)
  (cond
    ((eq 'INT typep) (atoi str))
    ((eq 'REAL typep) (atof str))
    ((eq 'STR typep) str)
    ((eq 'LIST typep) (@::string-to-list str ";"))
    ((eq 'SYM typep) (read str))
    (t str)))
(defun string:subst-all (str-new str-old str / inc len)
  (if (> (strlen str-old) 0)
    (progn
      (setq len (strlen str-new)
        inc 0)
      (while (setq inc (vl-string-search str-old str inc))
        (setq str (vl-string-subst str-new str-old str inc)
          inc (+ inc len)))))
  str)
(set '@::string-subst string:subst-all)
(defun string-capitalize (str)
  (strcat
    (string-upcase (substr str 1 1))
    (substr str 2)))
(defun strbytelen (x / codes)
  (setq codes (vl-string->list x))
  (+
    (length codes)
    (length
      (vl-remove-if
        (function (lambda (m) (< m 256)))
        codes))))


;; ── lib/version-utils.lsp ──────────────────────────────────────────
;; @depends string-utils
;; @provides version-utils
;; -*- coding: utf-8 -*-
;; Version comparison utilities extracted from base-function.lsp

(defun @::pad-version (lst len)
  (append lst (make-list (- len (length lst)) 0)))

(defun @::compare-version (new-ver old-ver / new-list old-list max-len)
  (if old-ver
    (progn
      (setq new-list (mapcar 'atoi (@::string-to-list new-ver ".")))
      (setq old-list (mapcar 'atoi (@::string-to-list old-ver ".")))
      (setq max-len (max (length new-list) (length old-list)))
      (setq new-list (@::pad-version new-list max-len))
      (setq old-list (@::pad-version old-list max-len))
      (progn
        (while (and new-list old-list (= (car new-list) (car old-list)))
          (setq new-list (cdr new-list) old-list (cdr old-list)))
        (and new-list (> (car new-list) (car old-list)))))
    t))


;; ── lib/file-utils.lsp ──────────────────────────────────────────
;; @depends string-utils
;; @provides file-utils
;; -*- coding: utf-8 -*-
;; File/path utilities extracted from base-function.lsp

(defun @::save-list-to-file (lst file / fp *error*)
  (setq *error* (lambda (msg)
      (@::cleanup-dcl msg fp file)
      (if (boundp '@::*error*) (@::*error* msg))))
  (setq fp (vl-catch-all-apply 'open (list (strcat @::*prefix* file) "w")))
  (if (not (vl-catch-all-error-p fp))
    (progn
      (foreach opt% lst (print opt% fp))
      (close fp))))

(defun @::path (path-str)
  (@::string-to-list (@::string-subst "/" "\\" path-str) "/"))

(defun @::parse-header (header-file / header line% fp *error*)
  (setq *error* (lambda (msg)
      (@::cleanup-dcl msg fp header-file)
      (if (boundp '@::*error*) (@::*error* msg))))
  (setq header nil)
  (if (eq 'STR (type-of header-file))
    (progn
      (if (findfile header-file)
        (progn
          (setq fp (vl-catch-all-apply 'open (list (findfile header-file) "r")))
          (if (and fp (not (vl-catch-all-error-p fp)))
            (progn
              (setq line% (read-line fp))
              (if line%
                (progn
                  (setq header (list (@::string-to-list line% " ")))
                  (while (setq line% (read-line fp))
                    (if (vl-string-search ": " line%)
                      (setq header (cons (@::string-to-list line% ": ") header))))))
              (close fp)
              (reverse header))))))))

(defun @::path-win-format (str)
  (@::string-subst "\\" "/" str))

(defun @::path-unix-format (str)
  (@::string-subst "/" "\\" str))

(defun @::path-os (str)
  (@::platform-path str))

(defun @::with-file-lines (path fn / fp line)
  (if (findfile path)
    (progn
      (setq fp (vl-catch-all-apply 'open (list path "r")))
      (if (not (vl-catch-all-error-p fp))
        (progn
          (while (setq line (read-line fp))
            (apply fn (list line)))
          (close fp))))))

(defun @::get-file-contents ( txtfile / contents fp line *error*)
  (setq *error* (lambda (msg)
      (@::cleanup-dcl msg fp txtfile)
      (if (boundp '@::*error*) (@::*error* msg))))
  (if (and (eq 'STR (type-of txtfile)) (findfile txtfile))
    (progn
      (setq fp (vl-catch-all-apply 'open (list txtfile "r")))
      (if (not (vl-catch-all-error-p fp))
        (progn
          (setq contents nil)
          (while (setq line (read-line fp))
            (setq contents (cons line contents)))
          (close fp)
          (setq contents (reverse contents))
          (apply 'strcat (mapcar (function (lambda (x) (strcat x "\n"))) contents)))))
    nil))

(defun @::mkdir (dir-list / dir-path dir%)
  (setq dir-path "")
  (foreach dir% dir-list
    (if (eq 'STR (type dir%))
      (cond
        ((= 58 (last (s2l dir%)))
          (setq dir-path (strcat dir-path dir%)))
        ((> (strlen dir%) 0)
          (setq dir-path (strcat dir-path "/" dir%))
          (if (null (findfile dir-path))
            (vl-mkdir dir-path)))))
  )
  dir-path)

(defun @::getenv (envname / res)
  (if (setq res (getenv envname))
    res
""))

(defun @::tmp-path ()
  (if (@::platform-is-linux-p)
    (strcat @::*tmp-path* (@::timestamp) "/")
    @::*tmp-path*))


;; ── lib/dcl.lsp ──────────────────────────────────────────
;; @depends string-utils file-utils
;; @provides dcl
;; -*- coding: utf-8 -*-;; DCL dialog utilities
;; Development source — see src/base-function.lsp for production
;; ═══════════════════════════════════════════════════════
;; DCL 抽象层 — 声明式对话框定义
;;;; 在 AutoLISP 中 :keyword 是普通符号（不会自求值），
;; 使用时必须放在 '() 中或显式 quote。
;;;; 格式: (:widget-type (:attr "val") (:attr2 "val2") child-spec...)
;;;; 示例:
;;   '(:dialog (:label "提示")
;;     (:text (:value "Hello"))
;;     (:ok-cancel))
;;;; 字符串值自动转义 DCL 特殊字符。
;; ═══════════════════════════════════════════════════════
(defun @::dcl-escape (str)
  "转义 DCL 字符串中的特殊字符 (引号、反斜杠)"
  (string:subst-all
    "\\\\"
    "\\"
    (string:subst-all "\\\"" "\"" str)))
(defun @::dcl-attrs-to-str (spec / attrs buf item)
  "将 '((:key \"val\") (:width 40)) 转为 DCL 属性字符串 \"key=\"val\";width=40;\""
  (setq buf nil)
  (foreach item spec
    (if (and (listp item) (>= (length item) 2) (eq 'SYM (type (car item))))
      (setq buf (cons
                  (strcat
                    (substr (vl-symbol-name (car item)) 2)
                    "="
                    (cond
                      ((eq 'STR (type (cadr item)))
                       (strcat "\"" (@::dcl-escape (cadr item)) "\""))
                      ((eq 'INT (type (cadr item)))
                       (itoa (cadr item)))
                      ((eq 'REAL (type (cadr item)))
                       (rtos (cadr item) 2 4))
                      (t (vl-prin1-to-string (cadr item))))
                    ";")
                  buf))))
  (if buf
    (setq attrs (apply 'strcat (reverse buf)))
    (setq attrs ""))
  attrs)
(defun @::dcl-widget-type-p (sym)
  "判断符号是否为 DCL 控件类型"
  (member
    sym
    '(:dialog :row :column :boxed-row :boxed-column :button :edit-box :list-box :popup-list :text :image :toggle
              :radio-button :radio-column :slider :spacer :spacer-0 :spacer-1 :ok-cancel :ok-only :ok-cancel-help :cancel-only)))
(defun @::dcl-attr-p (item)
  "判断列表项是否为 '(:key val) 形式的属性（vs 子控件）"
  (and
    (listp item)
    (= (length item) 2)
    (eq 'SYM (type (car item)))
    (= (ascii ":") (ascii (substr (vl-symbol-name (car item)) 1 1)))
    (null (@::dcl-widget-type-p (car item)))))
(defun @::dcl-gen (spec / wtype attrs children body)
  "将声明式 DCL 描述转为 DCL 源码字符串"
  (if (atom spec)
    (cond
      ((eq spec :spacer) ":spacer{}")
      ((eq spec :spacer-0) ":spacer_0{}")
      ((eq spec :spacer-1) ":spacer_1{}")
      (t ""))
    (progn
      (setq wtype    (car spec)
            attrs    nil
            children nil)
      (foreach item (cdr spec)
        (if (@::dcl-attr-p item)
          (setq attrs (cons item attrs))
          (setq children (cons item children))))
      (setq attrs    (reverse attrs)
            children (reverse children)
            body     (strcat
                       (@::dcl-attrs-to-str attrs)
                       (apply 'strcat (mapcar '@::dcl-gen children))))
      (cond
        ((eq wtype :dialog)
         (strcat "atlisp_dialog :dialog{" body "}"))
        ((eq wtype :row)
         (strcat ":row{" body "}"))
        ((eq wtype :column)
         (strcat ":column{" body "}"))
        ((eq wtype :boxed-row)
         (strcat ":boxed_row{" body "}"))
        ((eq wtype :boxed-column)
         (strcat ":boxed_column{" body "}"))
        ((eq wtype :button)
         (strcat ":button{" body "}"))
        ((eq wtype :edit-box)
         (strcat ":edit_box{" body "}"))
        ((eq wtype :list-box)
         (strcat ":list_box{" body "}"))
        ((eq wtype :popup-list)
         (strcat ":popup_list{" body "}"))
        ((eq wtype :text)
         (strcat ":text{" body "}"))
        ((eq wtype :image)
         (strcat ":image{" body "}"))
        ((eq wtype :toggle)
         (strcat ":toggle{" body "}"))
        ((eq wtype :radio-button)
         (strcat ":radio_button{" body "}"))
        ((eq wtype :radio-column)
         (strcat ":radio_column{" body "}"))
        ((eq wtype :slider)
         (strcat ":slider{" body "}"))
        ((eq wtype :spacer)
         (strcat ":spacer{" body "}"))
        ((eq wtype :ok-cancel) "ok_cancel;")
        ((eq wtype :ok-only) "ok_only;")
        ((eq wtype :ok-cancel-help) "ok_cancel_help;")
        ((eq wtype :cancel-only) "cancel_only;")
        (t
         (princ
           (strcat
             "\nWARN: unknown DCL widget: "
             (vl-symbol-name wtype)
             "\n"))
         "")))))
(defun @::dcl-dialog (spec setup-fn-fn)
  "从声明式定义创建并运行 DCL 对话框。
  spec: '(:dialog (:label \"Title\") child-spec...)
      setup-fn: (lambda () (action_tile \"key\" \"(setq result T)\"))
          返回 @::dcl-run-with-setup 的结果"
  ((lambda (dcl-str dcl-name)
     (@::dcl-run-with-setup dcl-name dcl-str dcl-name setup-fn-fn))
    (@::dcl-gen spec)
    (vl-symbol-name (gensym))))
;; ═══════════════════════════════════════════════════════
;; Existing DCL utilities (extracted from base-function.lsp)
;; ═══════════════════════════════════════════════════════
(defun @::open-url (url)
  (@::platform-open-url url))
(defun @::dcl-temp-path (name)
  (if (boundp '@::platform-temp-path)
    (@::platform-temp-path name)
    (cond
      ((@::platform-is-linux-p) (strcat @::*tmp-path* name ".dcl"))
      (t (vl-filename-mktemp name @::*tmp-path* ".dcl")))))
(defun @::cleanup-dcl (msg fp tmp)
  (if (eq 'file (type fp)) (close fp))
  (if (and (eq 'str (type tmp)) (findfile tmp)) (vl-file-delete tmp))
  (if (boundp '@::*error*) (@::*error* msg))
  (prin1 msg))
(defun @::dcl-run (dcl-name dcl-content dialog-name)
  (apply '@::dcl-run-with-setup (list dcl-name dcl-content dialog-name nil)))
(defun @::dcl-run-file (dcl-tmp dialog-name setup-fn / dcl-id *error*)
  (setq *error* (@::error-handler
                  '((if dcl-id (unload_dialog dcl-id))
                     (if (and (eq 'str (type dcl-tmp)) (findfile dcl-tmp))
                       (vl-file-delete dcl-tmp)))))
  (setq dcl-id (load_dialog dcl-tmp))
  (if (not (new_dialog dialog-name dcl-id))
    (progn
      (unload_dialog dcl-id)
      (vl-file-delete dcl-tmp)
      nil)
    (progn
      (if setup-fn (apply setup-fn nil))
      (start_dialog)
      (unload_dialog dcl-id)
      (vl-file-delete dcl-tmp)
      t)))
(defun @::dcl-run-with-setup (dcl-name dcl-content dialog-name setup-fn / dcl-tmp dcl-fp dcl-id *error*)
  (setq *error* (@::error-handler
                  '((if dcl-id (unload_dialog dcl-id))
                     (if (eq 'file (type dcl-fp)) (close dcl-fp))
                     (if (and (eq 'str (type dcl-tmp)) (findfile dcl-tmp))
                       (vl-file-delete dcl-tmp)))))
  (setq dcl-tmp (@::dcl-temp-path dcl-name))
  (setq dcl-fp (vl-catch-all-apply 'open (list dcl-tmp "w")))
  (if (not (vl-catch-all-error-p dcl-fp))
    (progn
      (foreach line (if (eq 'LIST (type dcl-content)) dcl-content (list dcl-content))
        (write-line line dcl-fp))
      (close dcl-fp)))
  (setq dcl-id (load_dialog dcl-tmp))
  (if (not (new_dialog dialog-name dcl-id))
    (progn
      (unload_dialog dcl-id)
      (vl-file-delete dcl-tmp)
      nil)
    (progn
      (if setup-fn (apply setup-fn nil))
      (start_dialog)
      (unload_dialog dcl-id)
      (vl-file-delete dcl-tmp)
      t)))

;; ── event-bus.lsp ──────────────────────────────────────────
;; @provides event-bus
(in-package :@)
(use-package :autolisp)
;; Self-contained event bus and module dependency system
;; All functions guard against unloaded dependencies
;; ┌─ 事件总线 ──────────────────────────────────────────────────────────────
;; │
;; │ @lisp 事件总线 — 轻量级发布/订阅模式，用于模块间解耦通信。
;; │
;; │ 核心概念:
;; │   事件名 (event-name) — 任意符号，如 'module-loaded、'network-status-changed
;; │   监听器 (handler-sym) — 一个函数符号，事件触发时被调用
;; │   参数列表 (arg-list)  — 传递给监听器的参数列表
;; │
;; │ API 一览:
;; │   @::event-on  event handler  — 注册监听器
;; │   @::event-off event handler  — 移除监听器
;; │   @::event-emit event [args]  — 触发事件
;; │   @::event-clear              — 清空所有事件
;; │
;; │ 使用示例:
;; │   ;; 定义监听器
;; │   (defun on-config-changed (args)
;; │     (princ (strcat "配置已变更: " (vl-prin1-to-string args))))
;; │
;; │   ;; 注册
;; │   (@::event-on 'config-changed 'on-config-changed)
;; │
;; │   ;; 触发（将调用 on-config-changed）
;; │   (@::event-emit 'config-changed '(font-size 14))
;; │
;; │   ;; 移除
;; │   (@::event-off 'config-changed 'on-config-changed)
;; │
;; │ 内置事件（由内核其他模块触发）:
;; │   module-loaded          — 模块加载完成
;; │   module-load-failed     — 模块加载失败
;; │   network-status-changed — 网络状态变化
;; │   config-changed         — 配置项变更
;; │   package-removed        — 包被移除
;; │   startup-complete       — @lisp 启动完成
;; │
;; └───────────────────────────────────────────────────────────────────────────
(setq @::*events* (list))
(defun @::event-add-handler (event-name handler-sym)
  "向 event-name 注册 handler-sym，内部辅助函数"
  (let ((entry (assoc event-name @::*events*)))
    (if entry
      (setq @::*events* (subst (cons event-name (cons handler-sym (cdr entry))) entry @::*events*))
      (setq @::*events* (cons (cons event-name (list handler-sym)) @::*events*)))))
(defun @::event-remove-handler (event-name handler-sym)
  "从 event-name 移除 handler-sym，内部辅助函数"
  (let ((entry (assoc event-name @::*events*)))
    (if entry
      (let ((new-handlers (vl-remove handler-sym (cdr entry))))
        (if new-handlers
          (setq @::*events* (subst (cons event-name new-handlers) entry @::*events*))
          (setq @::*events* (vl-remove entry @::*events*)))))))

(defun @::event-on (event-name handler-sym)
  "注册事件监听器。在 event-name 事件触发时调用 handler-sym 函数"
  "symbol"
  "(@::event-on 'config-changed 'on-config-changed)"
  (@::event-add-handler event-name handler-sym)
  handler-sym)

(defun @::event-off (event-name handler-sym)
  "移除指定事件上的监听器。handler-sym 不再响应 event-name"
  "symbol"
  "(@::event-off 'config-changed 'on-config-changed)"
  (@::event-remove-handler event-name handler-sym)
  handler-sym)
(defun @::event-emit (event-name arg-list)
  "触发事件，依次调用该事件上所有注册的监听器，传入 arg-list 作为参数"
  "nil"
  "(@::event-emit 'config-changed '(font-size 14))"
  (if (and arg-list (not (listp arg-list))) (setq arg-list (list arg-list)))
  (foreach h (cdr (assoc event-name @::*events*))
    (vl-catch-all-apply h (if arg-list (list arg-list) nil))))
(defun @::event-clear ()
  "清空所有事件监听器"
  "nil"
  "(@::event-clear)"
  (setq @::*events* (list)))
;; Module dependency system
(setq @::*module-deps* (list))
(defun @::module-def (module-name dep-list)
  "定义模块 module-name 的依赖列表 dep-list，用于按序自动加载"
  (if (not (listp dep-list)) (setq dep-list (list dep-list)))
  (if (not (assoc module-name @::*module-deps*))
    (setq @::*module-deps* (cons (cons module-name dep-list) @::*module-deps*))))
(defun @::module-load-with-deps (module-name / deps)
  "按依赖顺序加载模块：先加载所有依赖，再加载模块本身"
  (setq deps (cdr (assoc module-name @::*module-deps*)))
  (if (boundp '@::load-module)
    (progn
      (foreach dep deps
        (if (not (member dep @::*modules*))
          (@::load-module dep)))
      (@::load-module module-name))
    nil))
(defun @::module-loaded-p (module-name)
  "检查 module-name 是否已加载到 @::*modules* 中"
  (and (boundp '@::*modules*) (member module-name @::*modules*)))
T

;; ── base-function.lsp ──────────────────────────────────────────
;; @depends event-bus platform-api
;; @provides base-function
(in-package :@)
(use-package :autolisp)
(setq @::*acadver* (atof (getvar "acadver")))
(defun @::acadver () @::*acadver*)
(set '$platform (read (getvar "platform")))
;; (set 'textpage textscr)
;;  (if (@::platform-is-linux-p)
;;  (defun vla-postcommand (doc cmdstr)
;;    "Send a command string to the specified document, and return the result."
;;    (princ doc)
;;    (princ cmdstr)
;;    (command (vl-string-trim (chr 27) cmdstr))))
;; (set 'vla-postcommand vla-sendcommand)
(defun @::handle-keywords (expr)
  "处理关键字: 将 :xxx 形式的符号注册为当前包的关键字"
  "symbol or list"
  "(handle-keywords '(:foo bar))"
  (cond
    ((listp expr)
     (foreach item expr
       (if
         (and
           (eq (type-of item) 'sym)
           (= (ascii ":") (ascii (vl-symbol-name item))))
         (set item item)))
     expr)
    ((eq (type-of expr) 'sym)
     (if (= (ascii ":") (ascii (vl-symbol-name expr)))
       (set expr expr))
     expr)
    (t expr)))
(set 'handle-keywords @::handle-keywords)
;;(@::handle-keywords
;;  '(:dialog :row :column :boxed-row :boxed-column :button :edit-box :list-box :popup-list :text
;;            :image :toggle :radio-button :radio-column :slider :spacer :spacer-0 :spacer-1 :ok-cancel
;;           :ok-only :ok-cancel-help :cancel-only :label :value :key :width :height :alignment :fixed-width
;;            :fixed-height :children-alignment :children-fixed-width :children-fixed-height))
(defun @::timestamp (/ timestamp)
  "生成当前时间戳字符串 (Unix秒-毫秒)"
  "string"
  "(@::timestamp)"
  (setq timestamp (strcat
                    (rtos (* @::*seconds-per-day* (getvar "date")))
                    "."
                    (if (getvar "millisecs")
                      (itoa (abs (rem (getvar "millisecs") 10000)))
                      "0000"))))
(defun @::get-timer ()
  "获取高精度计时器值，兼容新版(毫秒)和旧版CAD(天)"
  "int or real"
  "(@::get-timer)"
  (if (> (@::acadver) @::*cad-20_1*)
    (getvar "MILLISECS")
    (getvar "TDUSRTIMER")))
(defun @::timer-elapsed-seconds (start)
  "计算从 start 到现在的秒数差，兼容 millisecs 和 TDUSRTIMER 两种计时"
  "number"
  "(@::timer-elapsed-seconds (@::get-timer))"
  (if (> (@::acadver) @::*cad-20_1*)
    (* 0.001 (- (@::get-timer) start))
    (* @::*seconds-per-day* (- (@::get-timer) start))))
(defun @::check-down-fails ()
  "检查下载失败次数是否超过阈值"
  (if (< @::*max-down-fails* @::*down-fail-times*)
    (progn
      (princ "\n*** @lisp: Too many download failures. ***\n")
      nil)
    t))
(defun @::leap-yearp (year)
  "判断年份是否为闰年"
  (and
    (= 0 (mod year 4))
    (or
      (/= 0 (mod year 100))
      (= 0 (mod year 400)))))
(set 'leap-yearp @::leap-yearp)
(defun @::confirm (lst-str / dcl-file dcl-fp dcl-id result *error*)
  "显示确认对话框，返回 T 或 nil"
  "T or nil"
  "(confirm '(\"Delete all?\"))"
  (setq *error* (@::error-handler
                  '((if dcl-id (unload_dialog dcl-id))
                    (if (and dcl-fp (eq 'FILE (type dcl-fp))) (close dcl-fp))
                    (if (and dcl-file (findfile dcl-file)) (vl-file-delete dcl-file)))))
  (if (not (listp lst-str)) (setq lst-str (list lst-str)))
  (setq dcl-file (@::dcl-temp-path "confirm")
        dcl-fp   (open dcl-file "w"))
  (write-line "atlisp_dialog :dialog{label=\"Confirm\";:spacer{}:column{" dcl-fp)
  (foreach str lst-str
    (write-line (strcat ":text{value=\"" (@::dcl-escape str) "\";}") dcl-fp))
  (write-line ":spacer{}ok_cancel;}}" dcl-fp)
  (close dcl-fp)
  (setq dcl-id (load_dialog dcl-file))
  (if (new_dialog "atlisp_dialog" dcl-id)
    (progn
      (action_tile "accept" "(done_dialog 1)")
      (action_tile "cancel" "(done_dialog 0)")
      (setq result (if (= (start_dialog) 1) t))
      (unload_dialog dcl-id)
      (vl-file-delete dcl-file))
    (progn
      (unload_dialog dcl-id)
      (vl-file-delete dcl-file)
      (setq result nil)))
  result)
(set 'confirm @::confirm)
(defun @::sleep (n / st)
  "等待 n 秒"
  "nil"
  "(sleep 0.5)"
  (if (minusp n) (setq n 0))
  (setq st (getvar "DATE"))
  (while (< (* @::*seconds-per-day* (- (getvar "DATE") st)) n)
    (princ)))
(set 'sleep @::sleep)
(defun @::tzoffset ()
  "获取当前时区偏移量(单位:秒)"
  (if (getvar "TDCREATE")
    (fix (/ (getvar "TDCREATE") (/ 1.0 24.0)))
    -8))
(setq @::*mktime-epoch* 2208988800)
(defun @::mktime1900 (lst / days-of-month)
  "将vl-file-systime转为int时间戳"
  ;;  '(0 31 28 31  30  31  30  31  31  30  31 30  31)
  ;; "将 lst 时间转为 从1900年01月01日经过的秒数"
  (setq days-of-month (if (leap-yearp (car lst))
                        '(0 31 60 91 121 152 182 213 244 274 305 335 366)
                        '(0 31 59 90 120 151 181 212 243 273 304 334 365)))
  (+
    @::*mktime-epoch*
    (*
      @::*minutes-per-hour*
      (+
        (*
          @::*minutes-per-hour*
          (+
            (*
              @::*hours-per-day*
              (+
                (* (- (car lst) 1970) 365)
                (fix (/ (- (car lst) 1970) 4))
                (nth (1- (nth 1 lst)) days-of-month)
                (nth 3 lst)))
            (nth 4 lst)
            (@::tzoffset)))
        (nth 5 lst)))
    (nth 6 lst)))
(defun consp (alist)
  "Verifies that an item is cons."
  (if
    (and
      (listp alist)
      (not (null alist)))
    T
    nil))
(defun pair (x y)
  "将两个列表合并为一个点对表的列表"
  (cond
    ((and (null x) (null y)) '())
    ((and (not (atom x)) (not (atom y)))
     (cons
       (list (car x) (car y))
       (pair (cdr x) (cdr y))))))
(defun getf (plist property / result)
  "从 plist 中获取 property 对应的值"
  (setq result
    (vl-member-if
      (function (lambda (x)
         (= (vl-prin1-to-string x) (vl-prin1-to-string property))))
      plist))
  (if result (cadr result) nil))
(defun @::getf (plist property) (getf plist property))
(defun @::evalsym (expr) "alias" (evalsym expr))
(defun @::evaltrans (expr) "alias" (evaltrans expr))
(defun evallst (expr) "alias" (@::evallst expr))
(defun evalsym (expr)
  "Evaluate a symbol or list of symbols, returning the result."
  (cond
    ((listp expr) (mapcar '@::evalsym expr))
    ((eq 'sym (type expr)) (eval expr))
    (t expr)))
(defun evaltrans (expr)
  "Evaluate a symbol or list of symbols, returning the result."
  (cond
    ((listp expr)
     (if (eq '_ (car expr))
       (eval (eval expr))
       (mapcar '@::evaltrans expr)))
    ((eq 'sym (type expr)) expr)
    (t expr)))
(defun @::evallst (expr)
  "Evaluate a list of expressions, returning a list of results."
  (cond
    ((atom expr) expr)
    ((eq 'subr (type (car expr))) (eval expr))
    ((listp expr) (mapcar '@::evallst expr))
    (t expr)))
(defun @::liveon (/ str-flag lst-contents acaddocfile fp)
  "检查 @lisp 是否已注册到 acaddoc.lsp 中，如果没有则注册"
  (setq str-flag (strcat
                   "(defun-q atlisp-startup ()"
                   "(if (and (null (eq 'subr (type @)))(null (eq 'subr (type @::load-config)))(findfile \"@lisp.fas\"))"
                   "(progn(vl-load-all \"@lisp\")(@::init-once))(@::init-once)))"
                   "(setq s::startup (append s::startup atlisp-startup))"))
  (if (setq acaddocfile (findfile "acaddoc.lsp"))
    (progn
      (setq lst-contents (reverse (@::string-to-list (@::get-file-contents acaddocfile) "\n")))
      (if
        (and
          (/= str-flag (car lst-contents))
          (/= str-flag (cadr lst-contents)))
        (if (setq fp (open acaddocfile "a"))
          (progn
            (write-line str-flag fp)
            (close fp)))
        (set '@::islive T)))))
(defun mapcan (fn lst)
  "Apply FN to each element of LST and concatenate the results."
  (apply 'append (mapcar fn lst)))
(defun make-list (n val / res)
  "Make a list of length N with each element VAL."
  (setq res nil)
  (repeat n (setq res (cons val res)))
  res)
;; Keep `@::remove-duplicates` here — not in lib
(defun @::remove-duplicates (lst / result)
  "Remove duplicate elements from LST, preserving order."
  (foreach item lst
    (if (not (member item result))
      (setq result (cons item result))))
  (reverse result))
(defun @::check-module-integrity (/ result func kind)
  "扫描 @::load-module 依赖链中所有函数的完整性。
   返回损坏函数列表: ((func-name . status) ...)
   status: unbound / nil / overwritten"
  (setq result '())
  (foreach func
    '(@::module-cooldown-p @::load-module-deps @::internetp @::fetch-module @::eval-module
                           ;; Level 1: @::internetp subtree
                           @::offline-mode-p @::check-cached-online @::probe-network-uris @::ax-request @::init-uris
                           @::uri
                           ;; Level 1: @::fetch-module subtree
                           @::uri-safe @::http-request @::cache-load-if-available
                           ;; Level 1: @::eval-module subtree
                           @::verify-module @::handle-module-failure @::event-emit @::cache-module-response
                           ;; Level 1: shared utilities
                           @::@log
                           ;; Level 2: cache subsystem
                           @::cache-load @::cache-store @::cache-ensure-dirs @::cache-timestamp
                           ;; Level 2: file utilities
                           @::get-file-contents))
  (setq kind (cond
               ((not (boundp func)) 'unbound)
                ((eq 'subr (type (vl-catch-all-apply '@::safe-eval (list func)))) 'ok)
                ((null (vl-catch-all-apply '@::safe-eval (list func))) 'nil)
               (t 'overwritten)))
  (if (not (eq 'ok kind))
    (setq result (cons (cons func kind) result)))
  (reverse result))


;; ── platform.lsp ──────────────────────────────────────────
;; @depends platform-api base-function
;; @provides platform
(defun @::set-locale (val)
  "设置 locale，确保值合法。"
  (if (member val '("chs" "cht" "en" "jp"))
    (setq @::*locale* val)
    (setq @::*locale* "chs")))
(defun @::get-locale ()
  "获取当前 locale。"
  @::*locale*)
(setq @::*fasext* ".fas")
(setq is-gstarcad     nil
      is-bricscad     nil
      is-zwcad        nil
      is-autocad      nil
      @::cad-platform (getvar "product"))
;; "中望，浩辰特殊定义"
;; zw2020  zrxvernum = "2018.40"
(cond
  ((or
     (string-equal "GstarCAD" @::cad-platform)
     (findfile "gcad.pgp"))
   (setq @::pgp-file "gcad.pgp")
    (@::set-locale "chs")
    (setq is-gstarcad T)
   (setq is-gcad T))
  ((or
     (wcmatch @::cad-platform "ZW*")
     (wcmatch @::cad-platform "SL*")
     (findfile "ZWCAD.pgp"))
    (setq @::pgp-file "ZWCAD.pgp")
    (@::set-locale "chs")
    (if (> (read (getvar "zrxvernum")) 2017)
      (setq @::*fasext* ".zelx"))
   (setq is-zwcad T))
  ((or
     (string-equal "bricscad" @::cad-platform)
     (string-equal "THCAD" @::cad-platform)
     (findfile "default.pgp"))
   (setq @::pgp-file "default.pgp")
   (setq is-bricscad T)
    (setq @::*fasext* ".des")
    (@::set-locale (strcase (getvar "locale") T)))
  ((string-equal "autocad" @::cad-platform)
   (setq @::pgp-file "acad.pgp")
   (setq is-autocad t)
    (cond
      ((= (getvar "syscodepage") "ANSI_936")
       (@::set-locale "chs"))
      ((= (getvar "syscodepage") "ANSI_950")
       (@::set-locale "cht"))
      (t (@::set-locale (strcase (getvar "locale") t)))))
   (t (@::set-locale "chs") (setq @::pgp-file "acad.pgp")))
(if (and (boundp 'command) (null (eq 'subr (type command))))
  (princ (strcat (_ "Internal function tampered") ": command")))
(setq @::cmd (if (eq 'subr (type command-s)) command-s (if vl-cmdf vl-cmdf command)))
(if (and is-gcad (>= (read (substr (getvar "gcadver") 2)) 24))
  (setq @::cmd command))
(if (not (boundp 'command-s)) (setq command-s @::cmd))
(setq @::fasext (lambda (file)
                  (strcat file @::*fasext*)))
;; 旧版兼容别名
(set 'fasext @::*fasext*)
(setq @::vlx (lambda (str-vlx)
               (if
                 (and
                   is-zwcad
                   (= ".vlx" (substr str-vlx (- (strlen str-vlx) 3))))
                 (setq str-vlx (strcat (substr str-vlx 1 (- (strlen str-vlx) 3)) ".vls"))
                 str-vlx)))
(defun @::sendcommand (obj-doc cmd-str)
  "向CAD发送命令"
  (cond
    (is-bricscad
     (vla-sendcommand cmd-str))
    (obj-doc
     (vla-sendcommand obj-doc cmd-str))
    (t
     (vla-sendcommand *DOC* cmd-str))))
(defun @::postcommand (obj-doc cmd-str)
  "向CAD发送命令2"
  (cond
    (is-bricscad
     (vla-postcommand cmd-str))
    (obj-doc
     (vla-postcommand obj-doc cmd-str))
    (t
     (vla-postcommand *DOC* cmd-str))))

;; ── version.lsp ──────────────────────────────────────────
;; @provides version
(setq @::*version* "1.23.8")
(set '@::version @::*version*)


;; ── constants.lsp ──────────────────────────────────────────
;; @provides constants
;; @depends version
;; Named constants for @lisp kernel
(in-package :@)

;; ── Time conversion ──
(setq @::*seconds-per-day*    86400.0
      @::*minutes-per-hour*   60.0
      @::*hours-per-day*      24.0
      @::*millisecs-per-sec*  1000
      @::*module-cooldown-ms* 30000)

;; ── CAD DATE unit fractions ──
(setq @::*date-30-seconds*    (/ 30.0 @::*seconds-per-day*)
      @::*date-5-minutes*     (/ 300.0 @::*seconds-per-day*))

;; ── HTTP status codes ──
(setq @::*http-status-ok*     200
      @::*http-status-continue* 100)

;; ── WinHTTP ──
(setq @::*winhttp-progid*  "WinHttp.WinHttpRequest.5.1"
      @::*winhttp-timeout* 5000)

;; ── CAD version thresholds ──
(setq @::*cad-20_1* 20.1)

;; ── Module cache ──
(setq @::*module-cache-ttl-days* 7)

;; ── Logging levels ──
(setq @::*log-level-debug*   0
      @::*log-level-info*    1
      @::*log-level-warn*    2
      @::*log-level-error*   3
      @::*log-level-fatal*   4)

;; ── Misc defaults ──
(setq @::*min-voice-len* 4)


;; ── bootstrap.lsp ──────────────────────────────────────────
;; @depends platform version base-function
;; @provides bootstrap
(in-package :@)
(setq @::progname "atlisp"
      start-time         (@::get-timer)
      $platform          (if (boundp '$platform) $platform (read (getvar "platform")))
      $userhome          (cond
                      ((@::platform-is-linux-p) (getenv "HOME"))
                      (t(getenv "userprofile")))
      @::*prefix*        (@::path-os (strcat $userhome "/@lisp/"))
      @::*prefix-config* (@::path-os (strcat $userhome "/.atlisp/")))
(setq @::*tmp-path* (@::path-os
                                  (if (getenv "temp")
                                    (strcat (getenv "temp") "\\")
                                    (strcat @::*prefix* "tmp/")))
      @::*app-tmp-path*         (strcat @::*prefix* "tmp/")
      @::*fingerprint-checksum* 246
      my-fingerprint            '(33 21 23 28 29 34 25 29 24))
(if (null @::*edition*) (setq @::*edition* "stable"))




;; ── error/safe-eval.lsp ──────────────────────────────────────────
;; @depends base-function platform
;; @provides error-safe-eval
(vl-load-com)
(setq @::*safe-eval-mode*   'relaxed ;; Security: Safe Eval
        ;; 'strict - 只允许白名单函数
        ;; 'relaxed - 允许所有函数（宽松模式）
)
(defun @::*safe-functions* ()
  "CAD 安全函数白名单，用于 @::safe-eval 限制 LLM/Agent 生成代码的可用函数"
  '(;; --- 核心 Lisp ---
    car cdr caar cadr cdar cddr caaar caadr cadar caddr cdaar cdadr cddar cdddr caaaar caaadr caadar
        caaddr cadaar cadadr caddar cadddr cdaaar cdaadr cdadar cdaddr cddaar cddadr cdddar cddddr cons
        list append reverse member assoc subst nth length mapcar apply remove foreach lambda
        ;; --- 谓词 ---
        = /= < > <= >= eq equal null not numberp listp atom type boundp minusp zerop
        ;; --- 数学 ---
        + - * / 1+ 1- abs atan cos sin exp expt fix float gcd log max min rem sqrt boole lsh logand
        logior
        ;; --- 字符串 ---
        strcat substr strlen strcase itoa atof rtos atoi chr ascii wcmatch vl-string-search
        vl-string-subst vl-string-trim vl-string-left-trim vl-string-right-trim vl-string-mismatch
        vl-string-position vl-string->list vl-list->string
        ;; --- 控制流 ---
        if cond progn while repeat setq set or and let let*
        ;; --- CAD 绘图 ---
        command entmake entmakex entmod entget entdel entlast entnext entsel nentsel nentselp handent
        ssget ssadd ssdel ssname sslength ssmemb ssgetfirst sssetfirst ssnamex
        ;; --- 系统变量 ---
        setvar getvar
        ;; --- 几何/坐标 ---
        angle polar distance inters trans osnap textbox
        ;; --- ActiveX ---
        vlax-invoke vlax-get-property vlax-put-property vlax-3D-point vlax-make-variant
        vlax-variant-value vlax-make-safearray vlax-safearray-fill vlax-safearray->list
        vlax-safearray-put-element vlax-safearray-get-element vlax-ename->vla-object
        vlax-vla-object->ename vlax-tmatrix vla-get-color vla-put-color vla-get-layer vla-put-layer
        vla-get-handle vla-get-objectname vla-delete vla-addline vla-addcircle vla-addtext vla-addmtext
        vla-addarc vla-addellipse vla-addpolyline vla-addspline vla-addrectangle vla-adddimension
        vla-addhatch vla-get-modelspace vla-get-paperspace vla-get-blocks vla-get-layers
        vla-get-textstyles vla-get-dimstyles vla-get-linetypes vla-get-views vla-get-viewports
        vla-startundomark vla-endundomark vla-get-insertionpoint vla-put-insertionpoint vla-get-rotation
        vla-put-rotation vla-get-height vla-put-height vla-get-width vla-put-width vla-get-textstring
        vla-put-textstring vla-get-radius vla-get-center vla-get-startpoint vla-get-endpoint
        vla-get-length vla-get-area vla-get-distance vla-get-normal vla-get-elevation vla-update
        vla-regen vla-get-activedocument vla-get-count vla-item vla-get-name
        ;; --- 用户输入 ---
        getpoint getstring getint getreal getdist getangle getorient getcorner getkword initget
        ;; --- 输出 ---
        princ print prin1 prompt terpri
        ;; --- 杂项 ---
        vl-position vl-some vl-every vl-member-if vl-remove-if vl-consp vl-list-length vl-list*
        vl-prin1-to-string vl-princ-to-string dist ang
        ;; --- @lisp 内核函数 ---
        @::safe-eval @::internetp @::http-request @::platform-http-get @::platform-http-post
        @::get-config @::set-config @::log-level @::event-on @::event-off @::event-emit
        @@))
(defun @::safe-fn-in-list-p (fn safe-fns)
  (and (= 'SYM (type fn)) (member fn safe-fns)))

(defun @::safe-form-p (form safe-fns)
  "递归检查 form 中所有函数调用是否在 safe-fns 白名单中"
  (cond
    ((atom form) t)
    ((listp form)
     ((lambda (fn)
        (cond
          ((@::safe-fn-in-list-p fn '(defun))
           (and
             (>= (length form) 3)
             (@::safe-form-p (cdddr form) safe-fns)))
          ((@::safe-fn-in-list-p fn '(lambda))
           (and
             (>= (length form) 2)
             (@::safe-form-p (cddr form) safe-fns)))
          ((@::safe-fn-in-list-p fn '(setq))
           ((lambda (ok tail)
              (while (and ok tail (cdr tail))
                (setq ok (@::safe-form-p (cadr tail) safe-fns))
                (setq tail (cddr tail)))
              ok)
             t
             (cdr form)))
          ((@::safe-fn-in-list-p fn '(if))
           (and
             (>= (length form) 2)
             (@::safe-form-p (cadr form) safe-fns)
             (if (> (length form) 2)
               (@::safe-form-p (caddr form) safe-fns)
               t)
             (if (> (length form) 3)
               (@::safe-form-p (cadddr form) safe-fns)
               t)))
          ((@::safe-fn-in-list-p fn '(cond))
           (vl-every
             (function (lambda (clause)
                (and
                  (listp clause)
                  (@::safe-form-p clause safe-fns))))
             (cdr form)))
          ((@::safe-fn-in-list-p fn '(while))
           (and
             (>= (length form) 2)
             (@::safe-form-p (cdr form) safe-fns)))
          ((@::safe-fn-in-list-p fn '(repeat))
           (and
             (>= (length form) 2)
             (@::safe-form-p (cdr form) safe-fns)))
          ((@::safe-fn-in-list-p fn '(foreach))
           (and
             (>= (length form) 3)
             (@::safe-form-p (cddr form) safe-fns)))
          ((@::safe-fn-in-list-p fn '(progn))
           (@::safe-form-p (cdr form) safe-fns))
          ((@::safe-fn-in-list-p fn '(or and))
           (@::safe-form-p (cdr form) safe-fns))
          ((@::safe-fn-in-list-p fn '(set))
           (and
             (>= (length form) 2)
             (@::safe-form-p (cadr form) safe-fns)))
          ((@::safe-fn-in-list-p fn '(let let*))
           (and
             (>= (length form) 2)
             (listp (cadr form))
             (vl-every
               (function (lambda (b)
                 (and (listp b) (>= (length b) 2)
                   (@::safe-form-p (cadr b) safe-fns))))
               (cadr form))
             (@::safe-form-p (cddr form) safe-fns)))
          ((@::safe-fn-in-list-p fn '(function))
           (and
             (>= (length form) 2)
             (if (and (listp (cadr form))
                      (@::safe-fn-in-list-p (caadr form) '(lambda)))
               (@::safe-form-p (cdadr form) safe-fns)
               t)))
          ((and (listp fn) (@::safe-fn-in-list-p (car fn) '(lambda)))
           (and
             (@::safe-form-p fn safe-fns)
             (@::safe-form-p (cdr form) safe-fns)))
           ((@::safe-fn-in-list-p fn safe-fns)
            (@::safe-form-p (cdr form) safe-fns))
           ((not (listp fn))
            (if (= 'sym (type fn)) nil t))
           (t nil)))
        (car form)))))
(defun @::safe-eval-mode (mode)
  "设置安全评估模式: 'strict（严格，默认）或 'relaxed（宽松，允许所有函数）"
  (setq @::*safe-eval-mode* mode)
  (princ
    (strcat
      (_ "\n@lisp 安全模式已切换为: ")
      (if (eq mode 'relaxed) (_ "宽松 (relaxed)") (_ "严格 (strict)"))
      "\n")))
(defun @::safe-eval (form)
  "安全地执行 form，只允许 @::*safe-functions* 中的函数
   设置 @::*safe-eval-mode* 为 'relaxed 可跳过检查（宽松模式）"
  (if
    (or
      (eq @::*safe-eval-mode* 'relaxed)
      (@::safe-form-p form (@::*safe-functions*)))
    (eval form)
    (progn
      (princ
        (strcat
          (_ "\n** @lisp 安全限制: 表达式含未授权函数调用，已阻止 **\n")
          (_ "设置 @::*safe-eval-mode* 为 'relaxed 进入宽松模式。\n")
          (vl-prin1-to-string form)
          "\n"))
      nil)))


;; ── error/handler.lsp ──────────────────────────────────────────
;; @depends base-function platform error-safe-eval
;; @provides error-handler error-handle
(setq @::*in-error-handler* nil
      @::*debug*            nil)
(defun @::error-handler (cleanup-forms)
  "创建标准错误处理函数。cleanup-forms 是清理表达式列表，在委托 @::*error* 前执行"
  "subr"
  "(@::error-handler '((close fp) (vl-file-delete tmp)))"
  (lambda (msg)
    (if cleanup-forms
      (foreach form cleanup-forms
        (vl-catch-all-apply 'eval (list form))))
    (if (boundp '@::*error*)
      (@::*error* msg)
      (princ msg))))
(defun @::try (body)
  "安全执行表达式，出错时返回错误对象（可用 vl-catch-all-error-p 检测）"
  "any"
  "(@::try '(/ 1 0))"
  (vl-catch-all-apply 'eval (list body)))
(defun @::try-or-nil (body)
  "安全执行表达式，出错时返回 nil。自动记录错误到日志"
  "any or nil"
  "(@::try-or-nil '(/ 1 0))"
  (let ((result (vl-catch-all-apply 'eval (list body))))
    (if (vl-catch-all-error-p result)
      (progn
        (@::@log "ERROR" (vl-catch-all-error-message result))
        nil)
      result)))
(defun @::*error* (msg / func)
  "统一的错误处理函数，提供自动修复建议"
  "nil"
  "(@::*error* \"no function definition: foo:bar\")"
  (vl-bt)
  (if @::*in-error-handler*
    (princ msg)
    (progn
      (setq @::*in-error-handler* t)
      (cond
        ((or
           (wcmatch msg "*无法应用特殊格式*")
           (wcmatch msg "*未知(command-s)失败*"))
         (progn
           (princ msg)
           (setvar "CMDECHO" 0)
           (if (null @::uri) (@::internetp))
           (if
             (or
               (null is-gcad)
               (and
                 (getvar "gcadver")
                 (>= (read (substr (getvar "gcadver") 2)) 23.9)))
             (command "start" (strcat (@::uri) "/faq.html#sec-1-2-6"))
             (command-s "start" (strcat (@::uri) "/faq.html#sec-1-2-6")))
           (setvar "cmdecho" 1)))
        ((wcmatch msg "no function definition:*")
         (princ msg)
         (if (@::internetp)
           (progn
             (if (null @::@get) (@::load-module 'network))
             (if (null fun::readme) (@::load-module 'function))
             (setq func (@::list-to-string
                          (mapcar
                            (function (lambda (x) (vl-string-trim " " x)))
                            (cdr (@::string-to-list msg ":")))
                          ":"))
             (if
               (and
                 (> (length (@::string-to-list func ":")) 1)
                 (member
                   (read (car (@::string-to-list func ":")))
                   (read (@::http-request (strcat (@::uri) "/function-category")))))
               (progn
                 (@::record-lib (car (@::string-to-list func ":")))
                 (@::load-lib)
                  (if (eq 'subr (type (vl-catch-all-apply '@::safe-eval (list (read func)))))
                   (progn
                     (princ "\n")
                     (@::@log "INFO" (_ "Some errors were found. fixed it!"))
                     (if (findfile (@::fasext "@lisp"))
                       (progn (load "@lisp") (@::init)))
                     (princ
                       (strcat
                         "\n"
                         (_ "Some errors were found. fixed it!")
                         "\n"
                         (_ "Please retry your operation."))))
                   (princ
                     (strcat
                       (_ "Please try to run (require '")
                       func
                       (_ ") or (require '")
                       (car (@::string-to-list func ":"))
                       ":*)"
                       (_ " to load the function definition from the web.")))))
               (princ msg)))))
        ((wcmatch msg "参数太*")
         (princ (strcat msg (_ ". Type (fun::usage function-name) for help."))))
        (t
         (princ msg)))
      (setq @::*in-error-handler* nil))))
(defun *error* (msg)
  "CAD 标准 *error* 函数，委托给 @::*error* 进行智能处理"
  "nil"
  ""
  (if (and (boundp '@::*error*) (null @::*in-error-handler*))
    (@::*error* msg)
    (progn
      (vl-bt)
      (princ msg)))
  (princ))

;; ── log.lsp ──────────────────────────────────────────
;; @depends error-handle
;; @provides log
(in-package :@)
(use-package :autolisp)
;; ============ Log Levels ============
(defun @::log-level (level / res)
  "返回日志级别的数字表示。接受符号、字符串或数字作为输入，并返回相应的日志级别编号。"
  (cond
    ((and (numberp level) (<= 0 level 4)) (fix level))
    (T
     (if
       (setq res (cdr
                   (assoc
                     level
                     '((DEBUG . 0)
                        (INFO . 1)
                        (WARN . 2)
                        (WARNING . 2)
                        (ERROR . 3)
                        (FATAL . 4)
                        ("DEBUG" . 0)
                        ("INFO" . 1)
                        ("WARN" . 2)
                        ("WARNING" . 2)
                        ("ERROR" . 3)
                        ("FATAL" . 4)
                        (0 . 0)
                        (1 . 1)
                        (2 . 2)
                        (3 . 3)
                        (4 . 4)))))
       res
       1))))
(defun @::log-level-name (level-num)
  "返回日志级别的名称。接受数字作为输入，并返回相应的日志级别名称字符串。"
  (if (and (numberp level-num) (>= level-num 0))
    (nth level-num '("DEBUG" "INFO" "WARN" "ERROR" "FATAL"))))
;; ============ State ============
(if (null (boundp '@::*log-buffer*))
  (setq @::*log-buffer* nil))
(if (null (boundp '@::*log-file*))
  (setq @::*log-file* nil))
(if (null (boundp '@::*log-session*))
  (setq @::*log-session* (strcat (rtos (getvar "cdate") 2 0))))
(setq @::*log-max-buffer*    100
      @::*log-max-files*     10
      @::*log-max-size*      1048576
      @::*log-console-level* 1
      @::*log-file-level*    0)
;; ============ Directory Setup ============
(defun @::log-ensure-dir (/ log-dir)
  "确认日志目录存在，如果不存在则创建它。返回日志目录路径。"
  (setq log-dir (strcat @::*prefix* "log"))
  (if (null (findfile log-dir))
    (vl-mkdir log-dir))
  log-dir)
;; ============ Timestamp ============
(defun @::log-timestamp ()
  "返回一个格式为 YYYYMMDDHHMMSS 的时间戳。"
  (vl-string-subst "" "." (rtos (getvar "cdate") 2 6)))
(defun @::log-readable-time (/ cdate date-part time-part)
  "返回一个人类可读的时间戳，格式为 YYYY-MM-DD HH:MM:SS。"
  (setq cdate     (getvar "cdate")
        date-part (fix cdate)
        time-part (- cdate date-part)
        date-part (rtos date-part 2 0)
        time-part (rtos time-part 2 6))
  (strcat
    (substr date-part 1 4)
    "-"
    (substr date-part 5 2)
    "-"
    (substr date-part 7 2)
    " "
    (substr time-part 2 2)
    ":"
    (substr time-part 4 2)
    ":"
    (substr time-part 6 2)))
;; ============ Log File Management ============
(defun @::log-file-path ()
  "返回当前日志文件的完整路径，确保日志目录存在。"
  (strcat
    (@::log-ensure-dir)
    "/session-"
    @::*log-session*
    ".log"))
(defun @::log-file-size (file)
  "返回指定日志文件的大小（以字节为单位），如果文件不存在则返回 0。"
  (if (findfile file)
    (vl-file-size file)
    0))
(defun @::log-rotate (/ file new-name)
  "检查当前日志文件是否超过最大大小，如果超过则旋转文件。使用时间戳重命名现有的日志文件并重置日志文件状态。"
  (setq file (@::log-file-path))
  (if
    (and
      (findfile file)
      (>= (@::log-file-size file) @::*log-max-size*))
    (progn
      (setq new-name (strcat file "." (@::log-timestamp)))
      (vl-file-rename file new-name)
      (setq @::*log-file* nil))))
(defun @::log-cleanup (/ log-dir files)
  "清理日志目录中的旧日志文件，只保留最新的 @::*log-max-files* 个文件。如果超出限制，则删除最旧的文件。"
  (setq log-dir (@::log-ensure-dir)
        files   (vl-remove-if
                  (function (lambda (f) (member f '("." ".."))))
                  (vl-directory-files log-dir "*.log*" 1))
        files   (vl-sort files (function (lambda (a b) (> (vl-file-size a) (vl-file-size b))))))
  (while (> (length files) @::*log-max-files*)
    (vl-file-delete (car (last files)))
    (setq files (reverse (cdr (reverse files))))))
;; ============ Core Logging ============
(defun @::log-format-entry (level-name msg)
  "格式化日志条目，包含时间戳、日志级别和消息。返回格式化的日志条目字符串。"
  (strcat
    "["
    (@::log-readable-time)
    "] ["
    level-name
    "] "
    msg))
(defun @::log-write-file (entry / file fp)
  "写入日志条目到日志文件。如果日志文件不存在，则创建它。确保在写入前进行日志轮换。"
  (@::log-rotate)
  (setq file (@::log-file-path)
        fp   (vl-catch-all-apply 'open (list file "a")))
  (if (and fp (not (vl-catch-all-error-p fp)))
    (progn
      (write-line entry fp)
      (close fp))))
(defun @::log-write-console (level-name msg)
  "将日志条目写入控制台，使用指定的日志级别和消息。使用括号和新行格式化输出。"
  (princ "[")
  (princ level-name)
  (princ "] ")
  (princ msg)
  (princ "\n"))
(defun @::log-internal (level-num msg / level-name entry)
  "Internal function to handle logging. Determines the log level name,
  formats the log entry, and writes it to the console and/or file based on the configured log levels. Returns the formatted log entry."
  (setq level-name (@::log-level-name level-num)
        entry      (@::log-format-entry level-name msg))
  (if (>= level-num @::*log-console-level*)
    (@::log-write-console level-name msg))
  (if (>= level-num @::*log-file-level*)
    (progn
      (setq @::*log-buffer* (cons entry @::*log-buffer*))
      (if (>= (length @::*log-buffer*) @::*log-max-buffer*)
        (@::log-flush))))
  entry)
;; ============ Public API ============
(defun @::log-flush (/ file fp)
  "Flushes the log buffer to the log file. Writes all buffered log entries to the log file and clears the buffer. Ensures that the log file is rotated if necessary."
  (if @::*log-buffer*
    (progn
      (@::log-rotate)
      (setq file (@::log-file-path)
            fp   (vl-catch-all-apply 'open (list file "a")))
      (if (not (vl-catch-all-error-p fp))
        (progn
          (foreach entry (reverse @::*log-buffer*)
            (write-line entry fp))
          (close fp)))
      (setq @::*log-buffer* nil))))
(defun @::@log (catalog str / level-num result)
  "记录日志消息，使用指定的目录和字符串。根据目录确定日志级别，格式化日志条目，并根据配置的日志级别将其写入控制台和/或文件。返回 nil。"
  (if (eq 'sym catalog)
    (setq catalog (strcase (vl-symbol-name catalog))))
  (setq level-num (@::log-level catalog))
  (if
    (or
      (>= level-num @::*log-console-level*)
      (>= level-num @::*log-file-level*))
    (setq result (@::log-internal level-num str)))
  (princ))
(defun @::@debug (catalog str / level-num)
  "记录调试消息，使用指定的目录和字符串。根据目录确定日志级别，格式化日志条目，并根据配置的日志级别将其写入控制台和/或文件。返回 nil。"
  (if (eq 'sym catalog)
    (setq catalog (strcase (vl-symbol-name catalog))))
  (setq level-num (@::log-level catalog))
  (if
    (and
      (boundp '@::get-config)
      (>= (@::get-config '@::@debug-mode) 2))
    (progn
      (setq @::*log-console-level* 0)
      (@::log-internal level-num str)
      (setq @::*log-console-level* 1)))
  (if
    (and
      (boundp '@::get-config)
      (>= (@::get-config '@::@debug-mode) 1))
    (progn
      (setq @::*log-file-level* 0)
      (@::log-internal level-num str)
      (setq @::*log-file-level* 0))))
(defun @::log-get-buffer (n / result count)
  "返回日志缓冲区中的条目列表。可选参数 n 指定返回的条目数量，默认为 20。"
  (if (null n) (setq n 20))
  (setq result nil
        count  0)
  (foreach entry @::*log-buffer*
    (if (< count n)
      (setq result (cons entry result)
            count  (1+ count))))
  (reverse result))
(defun @::log-status (/ file)
  "显示当前日志系统的状态，包括会话 ID、缓冲区大小、控制台和文件日志级别以及日志文件路径和大小。"
  (princ "\n=== @lisp Log Status ===\n")
  (princ (strcat "  Session: " @::*log-session* "\n"))
  (princ
    (strcat
      "  Buffer:  "
      (itoa (length @::*log-buffer*))
      " / "
      (itoa @::*log-max-buffer*)
      "\n"))
  (princ (strcat "  Console: >= " (@::log-level-name @::*log-console-level*) "\n"))
  (princ (strcat "  File:    >= " (@::log-level-name @::*log-file-level*) "\n"))
  (princ (strcat "  Path:    " (@::log-file-path) "\n"))
  (setq file (@::log-file-path))
  (if (findfile file)
    (princ (strcat "  Size:    " (itoa (@::log-file-size file)) " bytes\n")))
  (princ "==========================\n")
  (princ))
;; ============ Console Output Filtering ============
(defun @::log-set-console-level (level)
  "设置控制台日志输出的最低日志级别。接受符号、字符串或数字作为输入，并更新 @::*log-console-level* 变量。"
  (setq @::*log-console-level* (@::log-level level)))
(defun @::log-set-file-level (level)
  "设置文件日志输出的最低日志级别。接受符号、字符串或数字作为输入，并更新 @::*log-file-level* 变量。"
  (setq @::*log-file-level* (@::log-level level)))

;; ── i18n.lsp ──────────────────────────────────────────
;; @depends log
;; @provides i18n
(setq @::*i18n* '()
      @::*MT*   '()
      @::*lang* "en"
      @::*locale-loaded* nil)
(defun @::codepage2lang (codepage)
  "根据系统代码页返回语言标识符"
  (cdr
    (assoc
      codepage
      '(("ANSI_936" "zh" "zh_CN")
         ("ANSI_950" "cht" "zh_TW")
         ("ANSI_932" "jp" "jp")
         ("ANSI_949" "kor" "kr")
         ("ANSI_1258" "vie" "vi")))))
(setq @::*codepage* (vl-catch-all-apply 'getvar '("syscodepage")))
(if
  (not
    (vl-catch-all-error-p @::*codepage*))
  (setq @::*mtlang* (car (@::codepage2lang @::*codepage*))
        @::*lang*   (cadr (@::codepage2lang @::*codepage*))))
(if (null @::*lang*) (setq @::*lang* "en"))
(set '@::lang @::*lang*)
;;兼容旧版
(if (null @::*mtlang*) (setq @::*mtlang* "en"))
(defun @::update-locale (pkg-name / loc-file)
  "更新包的本地化语言"
  (if (eq 'sym (type pkg-name)) (setq pkg-name (strcase (vl-symbol-name pkg-name) t)))
  (setq loc-file (strcat @::*prefix* "locale/" pkg-name "." @::*lang* ".lang"))
  (if
    (or
      (@::check-newer-from-web (strcat "locale/" pkg-name "." @::*lang* ".lang"))
      (null (findfile loc-file)))
    (progn
      (if (null (member 'pkgman @::*modules*))
        (@::load-module 'pkgman))
      (@::down-lang pkg-name))))
(defun @::update-locale-all ()
  "更新所有包的本地化语言"
  (@::update-locale "@lisp")
  (foreach pkg @::*pkg-in-use*
    (@::update-locale pkg)))
(defun @::load-locale (pkg-name / fp opt% locale-paths)
  "加载包的本地化语言。如果包的区域设置已加载则跳过。"
  (if (eq 'sym (type pkg-name)) (setq pkg-name (strcase (vl-symbol-name pkg-name) t)))
  (if (member pkg-name @::*locale-loaded*)
    @::*i18n*
    (progn
      (setq locale-paths (list
                           (strcat @::*prefix* "locale/" pkg-name "." @::*lang* ".lang")
                           (strcat @::*prefix* "locale/" pkg-name ".zh.lang")
                           (strcat @::*prefix* "locale/" pkg-name ".en.lang")))
      (foreach locale-path locale-paths
        (if (findfile locale-path)
          (progn
            (setq fp (vl-catch-all-apply 'open (list locale-path "r")))
            (if (not (vl-catch-all-error-p fp))
              (progn
                (while (setq opt% (read-line fp))
                  (if (/= opt% "")
                    (setq @::*i18n* (cons (read opt%) @::*i18n*))))
                (close fp))))))
      (setq @::*i18n* (vl-remove nil @::*i18n*)
            @::*locale-loaded* (cons pkg-name @::*locale-loaded*))
      @::*i18n*)))
(defun @::mark-locale (str / res)
  "记录待翻译字串到文件"
  (if
    (and
      (or
        (/= @::*lang* "zh_CN")
        (< (@::max-char str) 128))
      (@::load-module 'network)
      @::machine-translate
      (not (member 10 (vl-string->list str))))
    (if (null (cdr (assoc str @::*MT*)))
      (if (setq res (@::machine-translate str nil nil))
        (progn
          (setq res     (string:subst-all "" "\n" res)
                @::*MT* (append @::*MT* (list (cons str res))))
          (@::save-mt)
          res)
        str)
      (cdr (assoc str @::*MT*)))
    str))
(defun @::load-mt (/ *error*)
  "加载包的本地化语言"
  (setq *error* (@::error-handler nil))
  (@::with-file-lines
    (strcat @::*prefix-config* "mt.lang")
    (function
      (lambda (opt%)
        (if (/= opt% "")
          (setq @::*MT* (cons (read opt%) @::*MT*))))))
  (setq @::*MT* (vl-remove nil (reverse @::*MT*))))
(defun @::save-mt (/ fp opt% *error*)
  "保存机器翻译的内容"
  (setq *error* (@::error-handler '((if (eq 'file (type fp)) (close fp)))))
  (if (findfile (vl-filename-directory @::*prefix-config*))
    (progn
      (setq fp (vl-catch-all-apply 'open (list (strcat @::*prefix-config* "mt.lang") "w")))
      (if (not (vl-catch-all-error-p fp))
        (progn
          (foreach opt% @::*MT*
            (print opt% fp))
          (close fp))))))
(defun @::clear-mt ()
  "清除机器翻译的内容"
  (if (findfile (strcat @::*prefix-config* "mt.lang"))
    (vl-file-delete (strcat @::*prefix-config* "mt.lang"))))
(defun @::_ (str / ret)
  "翻译标记,对未匹配的字串记录到单独的文件中，进行机器翻译。"
  (setq ret (cdr (assoc str (append @::*i18n* @::*MT*))))
  (if (vl-consp ret)
    (setq ret (car ret)))
  (if (eq 'str (type-of ret))
    (if (> (strlen ret) 0)
      ret
      (@::mark-locale str))
    (@::mark-locale str)))
(set '_ @::_)


;; ── net/ax-request.lsp ──────────────────────────────────────────
;; @depends base-function
;; @provides net
(vl-load-com)
;; ── WinHTTP connection pool ──
(setq @::*http-pool*      (list) ;; ((:obj . <COM>) :busy) ...
      @::*http-pool-max*  4 ;; max cached connections
      @::*http-pool-hits* 0)
(defun @::http-pool-acquire (/ pool obj)
  "从连接池中获取一个空闲的 WinHTTP 对象，池满时新建"
  (if (setq pool (vl-some (function (lambda (e) (if (null (cdr e)) e nil))) @::*http-pool*))
    (progn
      (setq @::*http-pool* (subst (cons (car pool) t) pool @::*http-pool*))
      (setq @::*http-pool-hits* (1+ @::*http-pool-hits*))
      (car pool))
    (if (< (length @::*http-pool*) @::*http-pool-max*)
      (progn
        (setq obj (vlax-create-object @::*winhttp-progid*))
        (setq @::*http-pool* (cons (cons obj t) @::*http-pool*))
        obj)
      nil)))
(defun @::http-pool-release (obj / entry)
  "将 WinHTTP 对象归还到连接池"
  (if (setq entry (assoc obj @::*http-pool*))
    (progn
      (setq @::*http-pool* (subst (cons obj nil) entry @::*http-pool*))
      t)
    (vlax-release-object obj)))
(defun @::http-pool-cleanup ()
  "释放连接池中所有 WinHTTP 对象"
  (foreach entry @::*http-pool*
    (vl-catch-all-apply 'vlax-release-object (list (car entry))))
  (setq @::*http-pool* nil))
(defun @::ax-request (uri / loopn return timestamp req)
  "尝试访问指定的 URI，返回 T 表示成功，nil 表示失败。"
  (cond
    ((@::platform-is-linux-p)
     (setq uri (@::shell-sanitize uri))
     (setvar "cmdecho" 0)
     (command
       "shell"
       (strcat
         "curl -s --head -o \""
         (@::shell-escape @::*tmp-path*)
         timestamp
         "\""
         " -H \"Atlisp-Version: "
         (@::shell-escape @::version)
         "\""
         " -H \"User-Agent: Atlisp-User\""
         " -H \"Locale: "
         (@::shell-escape @::*locale*)
         "\""
         (if @::*machineid* (strcat " -H \"MachineID: " (@::shell-escape @::*machineid*) "\"") "")
         " \""
         uri
         "\" 2>/dev/null"))
     (if (null (findfile (strcat @::*tmp-path* timestamp)))
       (command
         "shell"
         (strcat "wget -q --spider \"" uri "\" 2>/dev/null && touch \"" @::*tmp-path* timestamp "\"")))
     (setvar "cmdecho" 1)
     (setq loopn 0)
     (while
       (and
         (null (findfile (strcat @::*tmp-path* timestamp)))
         (< loopn @::*max-retries*))
       (setq loopn (1+ loopn))
       (sleep 0.5))
     (if (findfile (strcat @::*tmp-path* timestamp))
       (progn
         (vl-file-delete (strcat @::*tmp-path* timestamp))
         t)))
    (t
     (setq req (@::http-pool-acquire))
     (if (null req)
       (setq req (vlax-create-object @::*winhttp-progid*)))
     (@::set-timeouts req)
     (if req
       (progn
         (setq return (not
                        (vl-catch-all-error-p
                          (vl-catch-all-apply
                            (function
                              (lambda ()
                                (vlax-invoke req 'OPEN "HEAD" uri :vlax-false)
                                (@::set-headers req nil nil)
                                (vlax-invoke req 'Send)
                                (vlax-invoke req 'WaitforResponse @::*waitforresponse*)
                                (= (vlax-get-property req 'status) @::*http-status-ok*)))))))
         (@::http-pool-release req)
         return)))))

;; ── net/cache.lsp ──────────────────────────────────────────
;; @depends base-function
;; @provides net-cache
(defun @::cache-store-if-available (subdir key data ttl / result)
  "将数据存储到缓存中，如果缓存不可用则返回 nil。"
  (@::cache-ensure-dirs)
  (setq result (vl-catch-all-apply '@::cache-store (list subdir key data ttl)))
  (not (vl-catch-all-error-p result)))
(defun @::cache-load-if-available (subdir key max-age / result)
  "从缓存中加载数据，如果缓存不可用或过期则返回 nil。"
  (@::cache-ensure-dirs)
  (setq result (vl-catch-all-apply '@::cache-load (list subdir key max-age)))
  (if (vl-catch-all-error-p result) nil result))
(defun @::uri-safe (/ result)
  "获取当前的 URI，如果无法获取则返回 nil。"
  (setq result (vl-catch-all-apply (function (lambda () (@::uri))) nil))
  (if (vl-catch-all-error-p result) nil result))


;; ── net/checksum.lsp ──────────────────────────────────────────
;; @depends base-function
;; @provides net-checksum
(defun @::ash (int bits)
  "算术左移或右移整数 int 指定位数 bits。"
  (if (>= bits 0)
    (lsh int bits)
    (if (< int 0)
      (logior (lsh int bits) (lsh -1 (+ 32 bits)))
      (lsh int bits))))
(defun @::compute-checksum (str / sum lst)
  "计算字符串的校验和。"
  (setq sum 0
        lst (vl-string->list str))
  (foreach c lst
    (if (< c 128)
      (setq sum (boole 6 (+ (* sum 31) c) (@::ash sum -7)))))
  (itoa sum))
(setq @::*module-checksums* nil)
(defun @::verify-module (module response-str / content checksum expected)
  "验证模块的完整性。首次加载记录校验和，后续加载对比。"
  (setq expected (cdr (assoc module @::*module-checksums*)))
  (if expected
    (= (@::compute-checksum response-str) expected)
    (progn
      (setq content (vl-catch-all-apply 'read (list response-str)))
      (if (and (not (vl-catch-all-error-p content)) (listp content))
        (progn
          (setq @::*module-checksums* (cons (cons module (@::compute-checksum response-str))
                                            @::*module-checksums*))
          T)
        nil))))


;; ── net/headers.lsp ──────────────────────────────────────────
;; @depends base-function
;; @provides net-headers
(defun @::set-headers (req content-type content-length)
  "设置 HTTP 请求头。"
  (vl-load-com)
  (vlax-invoke req 'SetRequestHeader "Atlisp-Version" @::version)
  (vlax-invoke req 'SetRequestHeader "User-Agent" "Atlisp-User")
  (vlax-invoke req 'SetRequestHeader "Locale" @::*locale*)
  (if @::*machineid*
    (vlax-invoke req 'SetRequestHeader "MachineID" @::*machineid*))
  (if content-type
    (vlax-invoke req 'SetRequestHeader "Content-Type" content-type))
  (if content-length
    (vlax-invoke req 'SetRequestHeader "Content-Length" content-length)))
(defun @::set-headers-ext (req content-type content-length skip-user-agent extra-headers / i)
  "设置 HTTP 请求头，支持额外的自定义请求头。"
  (vlax-invoke req 'SetRequestHeader "Atlisp-Version" @::version)
  (if (not skip-user-agent)
    (vlax-invoke req 'SetRequestHeader "User-Agent" "Atlisp-User"))
  (vlax-invoke req 'SetRequestHeader "Locale" @::*locale*)
  (if @::*machineid*
    (vlax-invoke req 'SetRequestHeader "MachineID" @::*machineid*))
  (if content-type
    (vlax-invoke req 'SetRequestHeader "Content-Type" content-type))
  (if content-length
    (vlax-invoke req 'SetRequestHeader "Content-Length" content-length))
  (if extra-headers
    (progn
      (setq i 0)
      (while (< i (length extra-headers))
        (vlax-invoke
          req
          'SetRequestHeader
          (nth i extra-headers)
          (nth (1+ i) extra-headers))
        (setq i (+ i 2))))))
(defun @::set-timeouts (req)
  "设置 WinHTTP 超时时间。"
  (vl-catch-all-apply
    '(lambda ()
       (vlax-invoke req 'SetTimeouts
         @::*winhttp-timeout* @::*winhttp-timeout*
         @::*winhttp-timeout* @::*winhttp-timeout*))))
(defun @::http-ok-p (req)
  "检查 HTTP 响应状态是否为 200 OK。"
  (= (vlax-get-property req 'status) @::*http-status-ok*))


;; ── net/http.lsp ──────────────────────────────────────────
;; @depends log base-function
;; @provides net-http
#-sbcl
(defun @::http-post (uri post-data content-type)
  "发送 HTTP POST 请求。"
  (if (boundp '@::platform-http-post)
    (@::platform-http-post uri post-data content-type)
    (progn
      (@::@log "ERROR" "No HTTP POST backend available")
      nil)))
(defun @::http-request (uri)
  "发送 HTTP GET 请求。"
  (if (boundp '@::platform-http-get)
    (@::platform-http-get uri)
    (progn
      (@::@log "ERROR" "No HTTP backend available")
      nil)))


;; ── net/mid.lsp ──────────────────────────────────────────
;; @depends log base-function
;; @provides net-mid
(defun @::restore-mid ()
  "恢复 MachineID。仅从本地读取，网络获取延迟到 init Step 6。"
  (setq @::*machineid* (vl-catch-all-apply '@::platform-machineid nil))
  (if (or (vl-catch-all-error-p @::*machineid*) (null @::*machineid*))
    (setq @::*machineid* (@::read-register "MachineId"))))


;; ── net/module.lsp ──────────────────────────────────────────
;; @depends log event-bus base-function
;; @provides net-module
(defun @::module-cooldown-p (mod-sym / entry now)
  "检查模块是否处于冷却期。使用 MILLISECS 避免浮点精度问题。"
  (if (setq entry (assoc mod-sym @::*module-failures*))
    (progn
      (setq now (getvar "MILLISECS"))
      (if (< (- now (cadr entry)) @::*module-cooldown-ms*)
        (progn
          (setq @::*module-failures* (subst
                                       (list mod-sym now (1+ (caddr entry)))
                                       entry
                                       @::*module-failures*))
          t)
        (progn
          (setq @::*module-failures* (vl-remove entry @::*module-failures*))
          nil)))
    nil))
(defun @::load-module-deps (mod-sym module)
  "加载模块的依赖项。"
  (if (and (boundp '@::*module-deps*) (assoc mod-sym @::*module-deps*))
    (foreach dep (cdr (assoc mod-sym @::*module-deps*))
      (if (and (not (member dep @::*modules*)) (null (@::load-module dep)))
        (progn
          (@::@log "ERROR" (strcat "Failed to load dependency: " (vl-symbol-name dep)))
          (setq @::*modules* (vl-remove mod-sym @::*modules*))
          (setq mod-sym nil))))
    mod-sym))
(defun @::fetch-module (module cache-key / uri-str http-response response-str)
  "从远程服务器或缓存中获取模块的响应字符串。"
  (setq uri-str (@::uri-safe))
  (if (and uri-str (@::internetp))
    (progn
      (setq http-response (@::http-request
                            (strcat
                              uri-str
                              "/load-module?module="
                              (strcase module T)
                              "&edition="
                              @::*edition*)))
      (if http-response
        (if (not (vl-catch-all-error-p (vl-catch-all-apply 'read (list http-response))))
          (setq response-str http-response)
          (@::@log "WARN" (strcat "Truncated response for " module ", retrying...")))))
    (setq response-str (@::cache-load-if-available "modules" cache-key 1)))
  (list response-str http-response))
(defun @::cache-module-response (cache-key response-str)
  "将模块的响应字符串缓存到本地文件中。"
  (@::cache-ensure-dirs)
  (vl-catch-all-apply
    (function (lambda (/ fp mfp)
       (setq fp (open (strcat @::*cache-dir* "modules/" cache-key) "w"))
       (if fp (progn (princ (vl-prin1-to-string (read response-str)) fp) (close fp)))
       (setq mfp (open (strcat @::*cache-dir* "modules/" cache-key ".meta") "w"))
        (if mfp (progn (princ (list (@::cache-timestamp) @::*module-cache-ttl-days*) mfp) (close mfp)))))
    nil))
(defun @::handle-module-failure (mod-sym module)
  "处理模块加载失败的情况。"
  (@::@log "ERROR" module)
  (vl-catch-all-apply (function (lambda () (@::event-emit 'module-load-failed (list module)))) nil)
  (setq @::*modules*         (vl-remove mod-sym @::*modules*)
        @::*module-failures* (cons (list mod-sym (getvar "DATE") 1) @::*module-failures*))
  nil)
(defun @::eval-module (mod-sym module response-str http-response cache-key)
  "评估模块的响应字符串。"
  (if (vl-catch-all-error-p (vl-catch-all-apply 'read (list response-str)))
    (@::handle-module-failure mod-sym (strcat "Invalid module response: " module))
    (if (@::verify-module module response-str)
      (if (vl-catch-all-error-p (vl-catch-all-apply '@::safe-eval (list (read response-str))))
        (@::handle-module-failure mod-sym (strcat "Module eval failed: " module))
        (progn
          (setq @::*module-failures* (vl-remove
                                       (assoc mod-sym @::*module-failures*)
                                       @::*module-failures*))
          (vl-catch-all-apply (function (lambda () (@::event-emit 'module-loaded (list module)))) nil)
          (if http-response (@::cache-module-response cache-key response-str))
          t))
      (@::handle-module-failure mod-sym (strcat "Module verification failed: " module)))))
(defun @::load-module (module / response-str cache-key http-response mod-sym result)
  "加载指定的模块。"
  (if
    (and
      (null (@::check-module-integrity))
      (not (member 'network @::*modules*)))
    (progn
      (princ "\n** @lisp: @::load-module early integrity warning **\n")
      (princ "   Some internal functions appear to be overwritten.\n")
      (princ "   Run (C:@DIAG) for details.\n")))
  (if (eq 'sym (type module))
    (setq module (strcase (vl-symbol-name module) T)))
  (setq mod-sym (read module))
  (if (null mod-sym)
    nil
    (if (@::module-cooldown-p mod-sym)
      nil
      (if (member mod-sym @::*modules*)
        (setq @::*netstat* T)
        (progn
          (setq @::*modules* (cons mod-sym @::*modules*)
                mod-sym      (@::load-module-deps mod-sym module))
          (if (and mod-sym (null @::uri)) (@::internetp))
          (if (null mod-sym)
            nil
            (progn
              (setq cache-key     (strcat module "-" @::*edition*)
                    result        (@::fetch-module module cache-key)
                    response-str  (car result)
                    http-response (cadr result))
              (if response-str
                (@::eval-module mod-sym module response-str http-response cache-key)
                (progn
                  (setq @::*modules*         (vl-remove mod-sym @::*modules*)
                        @::*module-failures* (cons
                                               (list mod-sym (getvar "DATE") 1)
                                               @::*module-failures*))
                  nil)))))))))


;; ── net/probe.lsp ──────────────────────────────────────────
;; @depends event-bus base-function constants
;; @provides net-probe
;; ── Network circuit breaker ──
(vl-load-com)
(setq @::*network-failure-count*    0
      @::*network-circuit-open*     nil
      @::*network-circuit-threshold* 3
      @::*network-circuit-last-failure* 0)
(defun @::network-circuit-trip ()
  "记录网络失败，如果连续失败超过阈值则断开电路"
  (setq @::*network-failure-count* (1+ @::*network-failure-count*)
        @::*network-circuit-last-failure* (getvar "DATE"))
  (if (>= @::*network-failure-count* @::*network-circuit-threshold*)
    (setq @::*network-circuit-open* t))
  (@::@log "DEBUG" (strcat "Network failure "
    (itoa @::*network-failure-count*) "/" (itoa @::*network-circuit-threshold*))))
(defun @::network-circuit-reset ()
  "清除电路断开状态"
  (setq @::*network-failure-count* 0
        @::*network-circuit-open* nil))
(defun @::network-circuit-check ()
  "检查电路是否允许新请求。如果电路断开且冷却期已过，则自行重置。"
  (if @::*network-circuit-open*
    (if (< (- (getvar "DATE") @::*network-circuit-last-failure*) @::*date-30-seconds*)
      (progn
        (@::@log "DEBUG" "Network circuit open, skipping request.")
        nil)
      (progn
        (@::@log "DEBUG" "Circuit cooldown expired, resetting.")
        (@::network-circuit-reset)
        t))
    t))

(defun @::check-cached-online (cached / cached-uri req)
  "检查缓存的在线状态。"
  (setq cached-uri (if (listp cached) (cdr cached)))
  (if (and cached-uri (eq 'str (type cached-uri)))
    (progn
      (setq req (vlax-create-object @::*winhttp-progid*))
      (if (null req)
        t
        (progn
          (vlax-invoke req 'OPEN "HEAD" (strcat cached-uri "/state") :vlax-false)
          (@::set-headers req nil nil)
          (vlax-invoke req 'Send)
          (vlax-invoke req 'WaitforResponse @::*waitforresponse*)
          (if (= (vlax-get-property req 'status) @::*http-status-ok*)
            (progn
              (vlax-release-object req)
              (vl-catch-all-apply '@::safe-eval (list (list 'defun '@::uri nil cached-uri)))
              (@::init-uris)
              (@::cache-store "meta" "netstate" (cons 'online cached-uri) @::*date-5-minutes*)
              t)
            (progn
              (vlax-release-object req)
              (@::cache-invalidate "meta" "netstate")
              (@::internetp))))))
    t))
(defun @::probe-network-uris (/ req-path uris last-netstate)
  "尝试访问预定义的 URI 列表，找到第一个可访问的 URI 并返回。"
  (if (not (@::network-circuit-check))
    nil
    (progn
      (setq req-path (strcat
                       "/state"
                       (if @::*machineid* (strcat "?mid=" @::*machineid*) "?mid=")
                       (if @::cad-platform (strcat "&platform=" @::cad-platform) "")
                       (if @::acadver (strcat "&cadver=" (rtos (@::acadver))) ""))
            uris     @::*uris*)
      (while (and (car uris) (not (@::ax-request (strcat (car uris) req-path))))
        (setq uris (cdr uris)))
      (if (car uris)
        (progn
          (setq last-netstate (vl-bb-ref '@::netstate))
          (vl-bb-set '@::netstate 1)
          (if (not (= last-netstate 1))
            (vl-catch-all-apply
              (function
                (lambda () (@::event-emit 'network-status-changed (list 'online (car uris)))))
                nil))
          (vl-catch-all-apply '@::safe-eval (list (list 'defun '@::uri nil (car uris))))
          (@::init-uris)
          (@::cache-store "meta" "netstate" (cons 'online (car uris)) @::*date-30-seconds*)
          (@::network-circuit-reset)
          (car uris))
        (progn
          (setq last-netstate (vl-bb-ref '@::netstate))
          (vl-bb-set '@::netstate 0)
          (if (not (= last-netstate 0))
            (vl-catch-all-apply (function (lambda () (@::event-emit 'network-status-changed (list 'offline)))) nil))
          (@::network-circuit-trip)
          (@::cache-store "meta" "netstate" "OFFLINE" @::*date-30-seconds*)
          nil)))))
(defun @::internetp (/ cached)
  "检查是否有可用的互联网连接。"
  (if (@::offline-mode-p)
    (progn
      (@::@log "DEBUG" "Offline mode: skipping network check")
      nil)
    (progn
      (setq cached (if (setq cached (@::cache-load "meta" "netstate" @::*date-5-minutes*))
                     (read cached)))
      (cond
        ((and cached (or (eq cached 'online) (and (listp cached) (eq (car cached) 'online))))
         (@::check-cached-online cached))
        ((eq cached 'offline) nil)
        (t (@::probe-network-uris))))))

;; ── net/progress.lsp ──────────────────────────────────────────
;; @depends i18n
;; @provides net-progress
(defun @::progress-start (label)
  "启动进度显示。设置状态栏文本。"
  (setq @::*progress-label* label
        @::*progress-dots* 0)
  (princ (strcat "\n" label " "))
  (setvar "modemacro" (strcat "@lisp: " label " ...")))
(defun @::progress-tick ()
  "进度点动画。每隔 5 个点更新状态栏。"
  (setq @::*progress-dots* (1+ @::*progress-dots*))
  (princ ".")
  (if (= 0 (rem @::*progress-dots* 10))
    (princ (strcat " " (itoa @::*progress-dots*))))
  (if (= 0 (rem @::*progress-dots* 5))
    (setvar "modemacro" (strcat "@lisp: " @::*progress-label* " " (itoa @::*progress-dots*)))))
(defun @::progress-done ()
  "完成进度显示。"
  (princ (_ " done."))
  (princ "\n")
  (setvar "modemacro" ""))
(setq @::*progress-label* nil
      @::*progress-dots* 0)


;; ── net/proxy.lsp ──────────────────────────────────────────
;; @depends base-function
;; @provides net-proxy
(vl-load-com)
(defun @::proxy-running-p (/ shell exec stdout result)
  "通过 tasklist 检查 @proxy.exe 是否已在运行。"
  (vl-catch-all-apply
    (function
      (lambda (/ shell exec stdout result)
        (setq shell (vlax-get-or-create-object "WScript.Shell"))
        (setq exec  (vlax-invoke shell "Exec"
                      "tasklist /NH /FI \"IMAGENAME eq @proxy.exe\""))
        (setq stdout (vlax-get exec "StdOut"))
        (setq result (vlax-invoke stdout "ReadAll"))
        (vlax-release-object stdout)
        (vlax-release-object exec)
        (vlax-release-object shell)
        (vl-string-search "@proxy.exe" result)))))
(defun @::proxy ()
  "run proxy for cad in firewall (单例：仅启动一个 @proxy.exe 实例)"
  (if (findfile "@proxy.exe")
    (if (null (@::proxy-running-p))
      (progn
        (vl-catch-all-apply
          (function
            (lambda (/ shell)
              (setq shell (vlax-get-or-create-object "WScript.Shell"))
              (vlax-invoke shell "Run"
                (strcat "\"" @::*prefix* "@proxy.exe\" -p bin/") 0 :vl-false)
              (vlax-release-object shell))))
        (sleep 1)
        (@::internetp))
      (princ))
    (princ)))


;; ── net/registry.lsp ──────────────────────────────────────────
;; @depends base-function
;; @provides net-registry
(defun @::save-register (key str)
  "将字符串 str 保存到注册表中。"
  (if (boundp '@::platform-registry-write)
    (@::platform-registry-write key str)
    (if (not (@::platform-is-linux-p))
      (vl-registry-write "HKEY_CURRENT_USER\\Software\\atlisp.cn" key str))))
(defun @::read-register (key)
  "从注册表中读取键名为 key 的字符串值。"
  (if (boundp '@::platform-registry-read)
    (@::platform-registry-read key)
    (if (not (@::platform-is-linux-p))
      (vl-registry-read "HKEY_CURRENT_USER\\Software\\atlisp.cn" key))))
(defun @::shell-sanitize (str)
  "移除 shell 危险字符。"
  (vl-string-translate "`;$|&><(){}!^[]*?#~=\"\n\r'" "" str))
(defun @::shell-escape (str)
  "转义字符串，使其安全地放在 shell 双引号内使用。"
  (vl-string-translate "`$\"" "" str))


;; ── net/reload.lsp ──────────────────────────────────────────
;; @depends event-bus base-function
;; @provides net-reload
(defun @::reload-module (module / result)
  "重新加载模块：从已加载列表中移除、清除缓存、重新加载"
  (if (eq 'sym (type module))
    (setq module (strcase (vl-symbol-name module) T)))
  (setq @::*modules* (vl-remove (read module) @::*modules*))
  (vl-catch-all-apply
    (function (lambda ()
       (setq result (@::cache-invalidate "modules" (strcat module "-" @::*edition*)))))
    nil)
  (setq result (@::load-module module))
  (if result
    (vl-catch-all-apply (function (lambda () (@::event-emit 'module-reloaded (list module)))) nil))
  result)


;; ── net/uri.lsp ──────────────────────────────────────────
;; @depends i18n
;; @provides net-uri
(setq @::*uris* (if (member @::*lang* '("zh_CN" "zh_TW"))
                   '("http://s3.atlisp.cn"
                     "http://atlisp.cn"
                     "http://localhost:18100"
                     "http://localhost:8100")
                   '("http://atlisp.org"
                     "http://atlisp.cn"
                     "http://localhost:18100"
                     "http://localhost:8100")))
(if
  (and
    (boundp '@::get-config)
    (stringp (@::get-config '@::enterprise-registry))
    (/= "" (@::get-config '@::enterprise-registry)))
  (setq @::*uris* (cons (@::get-config '@::enterprise-registry) @::*uris*)))
(if @::*dev-mode*
  (setq @::*uris* (append '("https://dev.atlisp.cn" "http://dev.atlisp.cn") @::*uris*)))
(if (null (boundp '@::*max-retries*))
  (setq @::*max-retries* 10))
(if (numberp @::*waitforresponse*)
  T
  (set '@::*waitforresponse* 1000))
(if (null (boundp '@::*offline-mode*))
  (setq @::*offline-mode* nil))
(if (null (boundp '@::*offline-cache-only*))
  (setq @::*offline-cache-only* nil))
(defun @::offline-mode-p ()
  "检查是否处于离线模式。"
  (or
    @::*offline-mode*
    (and
      (vl-bb-ref '@::netstate)
      (= 0 (vl-bb-ref '@::netstate)))
    (and
      (boundp '@::*offline-cache-only*)
      @::*offline-cache-only*)))
(defun @::init-uris ()
  "初始化 URI 列表。"
  (cond
    ((= "http://localhost:18100" (@::uri))
     (setq @::*uri-ssl*   "http://localhost:18100"
           @::*uri-nossl* "http://localhost:18100"
           @::*uri-org*   "http://localhost:18101"
            @::*uri-chat*  "http://localhost:18102"))
    ((= "http://localhost:8100" (@::uri))
     (setq @::*uri-ssl*   "http://localhost:8100"
           @::*uri-nossl* "http://localhost:8100"
           @::*uri-org*   "http://localhost:8101"
           @::*uri-chat*  "http://localhost:8102"))
    (@::*dev-mode*
     (setq @::*uri-ssl*   "http://dev.atlisp.cn"
           @::*uri-nossl* "http://dev.atlisp.cn"
           @::*uri-org*   "http://atlisp.org"
           @::*uri-chat*  "https://openai.weixin.qq.com"))
    (t
     (setq @::*uri-ssl*   "https://atlisp.cn"
           @::*uri-nossl* "http://atlisp.cn"
           @::*uri-org*   "http://atlisp.org"
           @::*uri-chat*  "https://openai.weixin.qq.com"))))


;; ── net/wget.lsp ──────────────────────────────────────────
;; @depends base-function
;; @provides net-wget
#-sbcl
(set
  '@::wget
  (lambda (uri outfile extra-headers / cmd headers)
    (setq cmd     "curl -s -o"
          headers ""
          headers (strcat headers " -H \"Atlisp-Version: " (@::shell-escape @::version) "\"")
          headers (strcat headers " -H \"User-Agent: Atlisp-User\"")
          headers (strcat headers " -H \"Locale: " (@::shell-escape @::*locale*) "\""))
    (if @::*machineid*
      (setq headers (strcat headers " -H \"MachineID: " (@::shell-escape @::*machineid*) "\"")))
    (if extra-headers
      (setq headers (strcat headers " " extra-headers)))
    (setq uri     (@::shell-sanitize uri)
          outfile (@::shell-escape outfile))
    (setvar "cmdecho" 0)
    (command "shell" (strcat cmd " \"" outfile "\"" headers " \"" uri "\" 2>/dev/null"))
    (if (null (findfile outfile))
      (command "shell" (strcat "wget -q -O \"" outfile "\"" headers " \"" uri "\" 2>/dev/null")))
    (setvar "cmdecho" 1)
    outfile))


;; ── funlib/record.lsp ──────────────────────────────────────────
;; @depends net
;; @provides funlib-record
(setq @::*lib* '())
(defun @::record-lib (lib-name / fp)
  "记录所需的函数库"
  (if (eq 'str (type lib-name)) (setq lib-name (read lib-name)))
  (setq @::*lib-db* (if (findfile (strcat @::*prefix* @::*lib-file*))
                      (read (@::get-file-contents (strcat @::*prefix* @::*lib-file*)))))
  (if (null (member lib-name @::*lib-db*))
    (progn
      (setq @::*lib-db* (cons lib-name @::*lib-db*))
      (if (findfile (vl-filename-directory @::*prefix*))
        (progn
          (setq fp (vl-catch-all-apply 'open (list (strcat @::*prefix* @::*lib-file*) "w")))
          (if (not (vl-catch-all-error-p fp))
            (progn
              (print @::*lib-db* fp)
              (close fp))))))))
(defun @::load-lib ()
  "加载库"
  (if (findfile (strcat @::*prefix* @::*lib-file*))
    (foreach lib% (read (@::get-file-contents (strcat @::*prefix* @::*lib-file*)))
      (require (read (strcat (vl-symbol-name lib%) ":*"))))))


;; ── funlib/download.lsp ──────────────────────────────────────────
;; @depends net funlib-record
;; @provides funlib-download
(defun @::updatelib ()
  "更新本地库函数"
  (@::load-module 'function)
  (if
    (and
      (@::internetp)
      fun::updatelib)
    (fun::updatelib)))


;; ── funlib/browse.lsp ──────────────────────────────────────────
;; @depends net funlib-record funlib-download
;; @provides funlib-browse
(defun @::funhelp (fun-name)
  "显示函数帮助信息"
  (if fun-name
    (progn
      (if
        (and
          (or
            (eq 'subr (type fun-name))
            (eq 'usubr (type fun-name)))
          (eq
            'str
            (type (setq fun-name (caddr (@::string-to-list (vl-princ-to-string fun-name) " "))))))
        (setq fun-name (string-downcase (vl-string-trim ">" fun-name))))
      (@::load-module 'function)
      (mapcar
        (function (lambda (x) (princ (string:subst-all "  " "<br />" x)) (princ "\n")))
        (fun::description fun-name))
      (textpage))
    (princ
      "Not find function that you input. Please use quote to input (@::funhelp 'fun-name) try again."))
  (princ))
(defun @::funsrc (fun-name / tmp-uri)
  "显示函数源代码"
  (if fun-name
    (progn
      (if
        (and
          (or
            (eq 'subr (type fun-name))
            (eq 'usubr (type fun-name)))
          (eq
            'str
            (type (setq fun-name (caddr (@::string-to-list (vl-princ-to-string fun-name) " "))))))

        (setq fun-name (string-downcase (vl-string-trim ">" fun-name))
              tmp-uri  (strcat
                         "https://gitee.com/atlisp/atlisp-lib/tree/main/src/"
                         (string-downcase (string:subst-all "/" ":" fun-name))
                         ".lsp")))
      (@::load-module 'function)
      (mapcar
        (function (lambda (x) (princ x) (princ "\n")))
        (@::string-to-list (fun::src-code fun-name) "\n"))
      (princ "\n")
      (if tmp-uri
        (progn
          (princ (strcat "more: " tmp-uri "\n"))
          (princ "input @@W to visit the url\n")))
      (textpage))
    (princ
      "Not find function that you input. Please use quote to input (@::funhelp 'fun-name) try again."))
  (princ))
(defun @::funlist ()
  "函数列表"
  (@::load-module 'function)
  (fun::get-list))
(set '@::function-list fun::get-list)
(defun @::funsearch-fuzzy (str funlst allfunlst / score name)
  "模糊查询函数"
  (setq score 0)
  (foreach x allfunlst
    (setq name (vl-symbol-name x))
    (if
      (and
        (> (strlen name) (strlen str))
        (vl-string-search (strcase str) (strcase name)))
      (setq funlst (cons x funlst)
            score  (1+ score))))
  (if (> score 0)
    (progn
      (princ (strcat "; Fuzzy match found " (itoa score) " more functions.\n"))
      (foreach x (reverse funlst)
        (princ (strcat "  " (strcase (vl-symbol-name x) t) "\n"))))))
(defun @::funsearch (str / funlst allfunlst i)
  "显示前三个函数的用法"
  (if (eq 'sym (type str))
    (setq str (vl-symbol-name str)))
  (@::load-module 'function)
  (setq funlst (vl-remove
                 nil
                 (mapcar
                   (function
                     (lambda (x)
                       (if (wcmatch (vl-symbol-name x) (strcat "*" (strcase str) "*")) x)))
                   (setq allfunlst (fun::get-list)))))
  (princ (strcat "; " (itoa (length funlst)) " functions were found.\n"))
  (setq i 0)
  (if (> (length funlst) 0)
    (foreach x funlst
      (if (< (setq i (1+ i)) 4)
        (progn
          (princ "======================\n")
          (fun::help x))
        (progn
          (if (= i 4)
            (princ "======================\n"))
          (princ (strcase (vl-symbol-name x) t))
          (princ "\n"))))
    (@::funsearch-fuzzy str funlst allfunlst))
  (textpage)
  (princ))
(defun @::funexample (fun-name / example src)
  "函数用法示例"
  (if fun-name
    (progn
      (if
        (and
          (or
            (eq 'subr (type fun-name))
            (eq 'usubr (type fun-name)))
          (eq
            'str
            (type (setq fun-name (caddr (@::string-to-list (vl-princ-to-string fun-name) " "))))))
        (setq fun-name (strcase (vl-string-trim ">" fun-name) t)))
      (@::load-module 'function)
      (setq src     (read (fun::src-code fun-name))
            example (if (or (null (car (caddr src))) (eq '/ (car (caddr src))))
                      (strcat "(" (vl-symbol-name (cadr src)) ")")
                      (caddr (cdddr (read (fun::src-code fun-name))))))
      (if
        (and
          (eq 'str (type example))
          (/= "" example))
        (progn
          (princ (strcat " e.g : " example "\n Result => "))
          (vl-catch-all-apply '@::safe-eval (list (read example))))
        (progn
          (princ "Not find example code\n")
          (princ))))
    (progn
      (princ
        "Not find function that you input. Please use quote to input (@::funhelp 'fun-name) try again.")
      (princ))))
(set 'fun::search @::funsearch)
(set 'fun::list @::funlist)
(set 'fun::usage @::funhelp)
(set 'fun::help @::funhelp)
(set 'fun::src @::funsrc)
(set 'fun::run-example @::funexample)
(set 'fun::e.g @::funexample)
(defun @::loadlib ()
  "加载函数库"
  ;; 检查更新,首次安装
  (if
    (and
      (null (findfile ".cache/lib/lib-base.lsp"))
      (<= 1 (@::get-config '@::autoupdate))
      (@::load-module 'function)
      fun::autoupdatelib)
    (fun::autoupdatelib))
  (mapcar
    (function
      (lambda (libfile)
        (if (= "fail" (load (strcat ".cache/lib/" (vl-filename-base libfile)) "fail"))
          (progn
            (@::@log "ERROR" (strcat "load funlib " libfile " fail"))
            nil)
          t)))
    (directory (strcat @::*prefix* ".cache/lib/") "lib-*.lsp")))
(defun @::require-release (fun-match / @::*edition*)
  "引用 release 库"
  (setq @::*edition* "release")
  (@::require fun-match))
(set 'require @::require)
(set 'require-release @::require-release)
(set 'require-all @::loadlib)
(set 'import @::require)
(set 'import-all @::loadlib)
(set 'import-release @::require-release)
(setq @::*alias* '())
(defun @::defalias (sym-name sym-alias)
  "定义别名"
  (setq @::*alias* (cons (cons sym-name sym-alias) @::*alias*)))
(defun @::alias (sym-name sym-alias)
  "适用于符号只有一个 : 的情况,只对当前环境有效，以后新加的无效"
  "检查别名是否为原生函数类"
  (@::defalias sym-name sym-alias)
  (if (eq 'sym (type sym-name)) (setq sym-name (vl-symbol-name sym-name)))
  (if (eq 'sym (type sym-alias)) (setq sym-alias (vl-symbol-name sym-alias)))
  (foreach sym% (atoms-family 1)
    (if
      (and
        (> (length (@::string-to-list sym% ":")) 1)
        (eq sym-name (car (@::string-to-list sym% ":"))))
      (set
        (read (strcat sym-alias ":" (cadr (@::string-to-list sym% ":"))))
        (vl-catch-all-apply '@::safe-eval (list (read sym%))))))
  (princ))
(set 'alias @::alias)
(defun @::mapcar-alias ()
  "别名"
  (foreach op% @::*alias*
    (@::alias (car op%) (cdr op%))))


;; ── @lisp-env.lsp ──────────────────────────────────────────
;; @depends funlib-record
;; @provides @lisp-env
;; ============================================================
;; 重新加载入口
;; ============================================================
(defun @ () "" (if (findfile (@::fasext "@lisp")) (load "@lisp")) (@::init))
(in-package :@)
;; ============================================================
;; 核心系统文件清单
;; ============================================================
(setq @::*mini-sys-files* (list
                            (@::fasext "@lisp")
                            "@lisp.mnl"
                            "@lisp.dcl"
                            "@lisp.sld"
                            "@proxy.exe"
                            "bin/conf/nginx.conf"
                            "bin/conf/mime.types"))
;; ============================================================
;; 开发模式检测
;; ============================================================
(progn
  (setq @::*dev-mode-file* (strcat @::*prefix* "dev-mode"))
  (if (not (boundp '@::*dev-mode*))
    (setq @::*dev-mode* (if (findfile @::*dev-mode-file*) t))))
;; ============================================================
;; 版权信息
;; ============================================================
(setq @::*copyright*         '((Owner "VitalGG")
                                (nicknamechs "唯她")
                                (nicknameen "VitalGG")
                                (QQ "405842561")
                                (Email "vitalgg@foxmail.com")
                                (URI "http://atlisp.cn")
                                (URI-en "http://atlisp.org")
                                (Discord "https://discord.gg/atlisp")
                                (Bilibili "https://space.bilibili.com/atlisp")) ;; 全局系统变量
      @::*study-mode*        0 ; 学习模式
      @::*modules*           '() ; 已加载的模块列表
      @::*local-pkgs*        '() ; 本地包及已下载的包信息
      @::*pkg-in-use*        '() ; 运行 CAD 时要加载的包
      @::*pkg-state*         '() ; 已加载的包
      @::*pkgs*              '() ; 所有系统包列表 (pkgs.list)
      @::*pkgs-release*      '() ; 先行版系统包列表 (pkgs.list)
      @::*pkgs-category*     '() ; 包分类
      @::*netstat*           nil
      @::*lib-file*          "lib.cfg"
      @::*lib-db*            '()
      @::*config-file*       "config.cfg"
      @::*config-default*    '() ; 缺省配置
      @::*config-db*         '() ; 当前配置
      @::*bootstrap-state*   nil
      @::*debug-mode*        0 ; 调试模式
      @::*decimal-places*    3 ; 数值精度
      @::*curl*              (if (@::platform-is-linux-p)
                               "curl"
                               (if (= "AMD64" (@::getenv "PROCESSOR_ARCHITECTURE"))
                                 (strcat "bin\\curl.exe")
                                 (strcat "bin\\curl-w32.exe"))) ;; 版本模式
      @::*release-mode-file* (strcat @::*prefix* "release-mode"))
(if (findfile @::*release-mode-file*)
  (setq @::*edition* "release"))
;; ============================================================
;; 系统状态标志
;; ============================================================
(setq @::*flag-damage*           0 ; 系统损坏标志
      @::*flag-menu-need-update* nil ; 菜单需更新标志
      @::*max-down-fails*        100 ; 最大下载失败次数
      @::*max-init-times*        100 ; 最大初始化尝试次数
      @::*down-fail-times*       0 ; 当前下载失败次数
      @::*init-times*            0 ; 当前初始化次数
)

;; ── setup.lsp ──────────────────────────────────────────
;; @depends @lisp-env net
;; @provides setup
(setq @::*curl-x64-min-size* 4247672
      @::*curl-w32-min-size* 3699832
      @::*bin-subdirs*       '("bin/conf" "bin/logs" "bin/temp"))
(defun @::check-uploader ()
  "检查上传器"
  (if (= "AMD64" (getenv "PROCESSOR_ARCHITECTURE"))
    (if (findfile "bin/curl.exe")
      (if (> @::*curl-x64-min-size* (vl-file-size (findfile "bin/curl.exe")))
        nil
        T))
    (if (findfile "bin/curl-w32.exe")
      (if (> @::*curl-w32-min-size* (vl-file-size (findfile "bin/curl-w32.exe")))
        nil
        T))))
(defun @::down-uploader ()
  "下载上传器"
  (if (null (eq 'subr (type @::down-file)))
    (@::load-module 'pkgman))
  (or
    (findfile "bin/curl-ca-bundle.crt")
    (@::down-file "bin/curl-ca-bundle.crt"))
  (if (= "AMD64" (getenv "PROCESSOR_ARCHITECTURE"))
    (if (null (findfile "bin/libcurl-x64.dll"))
      (progn
        (@::down-file "bin/libcurl-x64.dll")
        (@::down-file "bin/curl.exe")
        (@::@log "INFO" (_ "downloading curl.exe, this need longer time，Please waitting..."))
        nil)
      (if (> @::*curl-x64-min-size* (vl-file-size (findfile "bin/curl.exe")))
        (progn
          (@::@log "INFO" (_ "downloading curl.exe, this need longer time，Please waitting..."))
          nil)
        T))
    (if (null (findfile "bin/libcurl.dll"))
      (progn
        (@::down-file "bin/libcurl.dll")
        (@::down-file "bin/curl-w32.exe")
        (@::@log "INFO" (_ "downloading curl.exe, this need longer time，Please waitting..."))
        nil)
      (if (> @::*curl-w32-min-size* (vl-file-size (findfile "bin/curl-w32.exe")))
        (progn
          (@::@log "INFO" (_ "downloading curl.exe, this need longer time，Please waitting..."))
          nil)
        T))))
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;; 计算并生成本工具集所在目录 @::*prefix*
;;; 添加文件搜索目录及信任目录,建立运行环境。
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
(defun @::add-path-in-acadprefix (path / path-env)
  "添加 path 到搜索目录表"
  (setq path-env (if is-gcad "GCAD" "ACAD")
        path     (@::path-os path))
  (if (null (member (strcase path) (mapcar 'strcase (@::string-to-list (getenv path-env) ";"))))
    (setenv
      path-env
      (@::path-os
        (strcat
          path
          ";"
          (vl-string-right-trim ";" (getenv path-env))
          ";")))))
(defun @::remove-path-in-acadprefix (path / path-env)
  "从搜索目录表删除path"
  (setq path-env (if is-gcad "GCAD" "ACAD")
        path     (@::path-os path))
  (if (member (strcase path) (mapcar 'strcase (@::string-to-list (getenv path-env) ";")))
    (setenv
      path-env
      (@::path-os
        (strcat
          (@::list-to-string
            (vl-remove-if
              (function
                (lambda (x)
                  (=
                    (strcase path)
                    (strcase x))))
              (@::string-to-list (getenv path-env) ";"))
            ";")
          ";")))))
(defun @::fix-path ()
  "修复 @lisp 目录"
  (@::mkdir (@::path (strcat $userhome "/@lisp")))
  (@::mkdir (@::path (strcat (@::getenv "appdata") "/@lisp")))
  (@::mkdir (@::path (strcat $userhome "/.atlisp")))
  (mapcar
    (function (lambda (x) (@::mkdir (@::path (strcat @::*prefix* x)))))
    (append '("locale" "packages" "bin" "archives" "log" "lib" ".cache" ".cache/lib")
            @::*bin-subdirs*))
  (cond
    ((and is-zwcad (< (read (getvar "zrxvernum")) 2017))
     (@::alert "This ZWCAD version CAN NOT add @lisp path  into search paths,Please add it manually."))
    (t
     (@::add-path-in-acadprefix (@::path-os (strcat (@::getenv "appdata") "/@lisp")))
     (@::add-path-in-acadprefix (@::path-os (strcat $userhome "/@lisp")))))
  (@::mkdir (@::path @::*tmp-path*))
  (@::mkdir (@::path @::*app-tmp-path*)))
(defun @::add-domain-in-trusteddomains (domain)
  "从 domain 添加到信任域名表"
  (if
    (and
      (>= (atof (getvar "acadver")) 19.0)
      (getvar "trusteddomains"))
    (if
      (null
        (member
          (strcase domain)
          (mapcar
            'strcase
            (@::string-to-list (getvar "trusteddomains") ";"))))
      (setvar
        "trusteddomains"
        (strcat
          (vl-string-right-trim ";" (getvar "trusteddomains"))
          ";"
          domain)))))
;; 修正信任目录
(defun @::add-path-in-trustedpaths (path)
  "将path 添加到任目录表"
  (if (vl-file-directory-p (vl-string-right-trim "." path))
    (if
      (and
        (>= (atof (getvar "acadver")) 19.0)
        (getvar "trustedpaths"))
      (if
        (null
          (member
            (strcase path)
            (mapcar
              'strcase
              (@::string-to-list (getvar "trustedpaths") ";"))))
        (setvar
          "trustedpaths"
          (strcat
            (vl-string-right-trim ";" (getvar "trustedpaths"))
            ";"
            path
            ";"))))))
(defun @::remove-path-in-trustedpaths (path)
  "从信任目录表中删除path"
  (if
    (and
      (>= (atof (getvar "acadver")) 19.0)
      (getvar "trustedpaths"))
    (if
      (member
        (strcase path)
        (mapcar
          'strcase
          (@::string-to-list (getvar "trustedpaths") ";")))
      (setvar
        "trustedpaths"
        (strcat
          (@::list-to-string
            (vl-remove-if
              (function
                (lambda (x)
                  (=
                    (strcase path)
                    (strcase x))))
              (@::string-to-list (getvar "trustedpaths") ";"))
            ";")
          ";")))))
(if @::*uris*
  (mapcar
    (function (lambda (x) (@::add-domain-in-trusteddomains (cadr (@::string-to-list x "://")))))
    @::*uris*))
(defun @::check-pgp (/ fp str)
  "检查 acad.pgp 文件是否有 @lisp 的运行环境"
  (if
    (and
      (findfile @::pgp-file)
      (setq fp (vl-catch-all-apply 'open (list (findfile @::pgp-file) "r")))
      (not (vl-catch-all-error-p fp)))
    (progn
      (while (setq str (read-line fp))
        (if (= (substr str 1 15) "powershell-bg,C")
          (setq @::*enable-start* T)))
      (close fp)))
  @::*enable-start*)
(defun @::ensure-start-enabled ()
  "确认可引导"
  (or
    @::*enable-start*
    (@::check-pgp)
    (@::patch-pgp)))
(defun @::find-powershell (/ pspath)
  "查找 PowerShell 可执行文件路径。"
  (cond
    ((and (setq pspath (vl-registry-read
                         "HKEY_LOCAL_MACHINE\\SOFTWARE\\Microsoft\\PowerShell\\1\\PowerShellEngine"
                         "ApplicationBase"))
          (eq 'STR (type pspath)))
     (strcat pspath "\\powershell.exe"))
    ((findfile (strcat (getenv "windir") "\\System32\\WindowsPowerShell\\v1.0\\powershell.exe"))
     (strcat (getenv "windir") "\\System32\\WindowsPowerShell\\v1.0\\powershell.exe"))
    (t "")))
(defun @::write-pgp-commands (pgp-file path-powershell / fp-acadpgp)
  "向 PGP 文件写入自定义命令。"
  (setvar "cmdecho" 0)
  (if (and (findfile pgp-file)
           (setq fp-acadpgp (vl-catch-all-apply 'open (list (findfile pgp-file) "a")))
           (not (vl-catch-all-error-p fp-acadpgp)))
    (progn
      (write-line (string:from-list
        (list "" "start,start,4,*runapp:,"
              "notepad,start notepad,1,*editfile:,"
              (strcat "powershell," path-powershell ",4,*powershell:,")
              (strcat "powershell-bg," path-powershell ",5,*powershell:,")
              "start-bg,start,5,*runapp:,"
              "shell-bg,  ,5,*runapp:,"
              "AWAIT,  ,4,*runpromise:,") "\n") fp-acadpgp)
      (close fp-acadpgp)
      (setvar "re-init" (if (or (and is-zwcad (< (read (getvar "zrxvernum")) 2017)) is-bricscad)
                          0 16))
      (setvar "cmdecho" 1)
      (print (strcat pgp-file " ready."))
      t)
    (@::@log "WARN" "Not have permission to write .pgp file.")))
(defun @::patch-pgp (/ pgp-file fp-acadpgp patch-ok path-powershell)
  "修复pgp"
  (setq *error* (@::error-handler nil))
  (setq patch-ok nil)
  (if (null @::*enable-start*) (@::check-pgp) (sleep 2))
  (setq pgp-file @::pgp-file)
  (if (null (findfile pgp-file))
    (setq fp-acadpgp (vl-catch-all-apply 'open
                        (list (@::path-os (strcat (vl-string-right-trim "\\/" (getvar "ROAMABLEROOTPREFIX"))
                                                  "/Support/" pgp-file)) "a")))
    (if (not (vl-catch-all-error-p fp-acadpgp))
      (progn (write-line "" fp-acadpgp) (close fp-acadpgp))))
  (setq path-powershell (@::find-powershell))
  (if (and (null @::*enable-start*) (findfile path-powershell))
    (setq patch-ok (@::write-pgp-commands pgp-file path-powershell))
    (@::alert (_ "Not found powershell or your system can NOT support for network")))
  patch-ok)
(defun @::install (/ *error* fp-mnl n return s h o v e r)
  "安装"
  (setq *error* (@::error-handler nil))
  (prompt (strcat (_ "修复@lisp支持路径。") "\n"))
  (@::fix-path)
  (if (not (@::platform-is-linux-p))
    (progn
      (@::add-path-in-trustedpaths (strcat (getenv "userprofile") "\\@lisp\\..."))
      (@::add-path-in-trustedpaths (strcat (getenv "appdata") "\\@lisp\\..."))))
  (if
    (and
      (@::internetp)
      (@::load-module 'network))
    (progn
      (prompt (strcat (_ "安装核心系统。") "\n"))
      (@::install-mini-sys)
      (if (null (findfile "@lisp.mnu"))
        (progn
          (@::make-menu)
          (prompt "@lisp was installed. Please input @H for help.\n")
          t)))
    (if
      (and
        (null (findfile (strcat @::*prefix* "@lisp.mnl")))
        (not (@::platform-is-linux-p)))
      (progn
        (setq fp-mnl (vl-catch-all-apply 'open (list (strcat @::*prefix* "@lisp.mnl") "w")))
        (if (not (vl-catch-all-error-p fp-mnl))
          (progn
            (write-line
              (vl-prin1-to-string
                '(progn
                   (defun @::init-placemenu (/ n)
                     "初始化@lisp菜单位置"
                     (if (menugroup "@LISP")
                       (progn
                         (setq n 1)
                         (while
                           (and
                             (< n 24)
                             (menucmd (strcat "P" (itoa n) ".1=?")))
                           (setq n (+ n 1)))
                         (progn
                           (setq n (if (> n 3)
                                     (- n 2)
                                     3))
                           (menucmd (strcat "p" (itoa n) "=+@LISP.POP1"))))))
                   (@::init-placemenu)
                   (vl-load-com)
                   (if
                     (and
                       (null (member (type @) '(subr xsubr)))
                       (null (member (type @::load-config) '(subr xsubr)))
                       (or (findfile "@lisp.fas") (findfile "@lisp.zelx") (findfile "@lisp.des")))
                     (if
                       (vl-catch-all-error-p
                         (setq return (vl-catch-all-apply
                                        (function (lambda () (vl-load-all "@lisp"))))))
                       ;;load fail.then load from web
                       (if (eq 'Microsoft (read (getvar "platform")))
                         (progn
                           (vl-load-com)
                           (setq s strcat
                                 h "http"
                                 o (vlax-create-object (s "win" h ".win" h "request.5.1"))
                                 v vlax-invoke
                                 e eval
                                 r read)
                           (v
                             o
                             'open
                             "get"
                             (s
                               h
                               "://"
                               (if (findfile (s (getenv "userprofile") "/@lisp/dev-mode")) "dev." "")
                               "atlisp."
                               "cn/boot")
                             :vlax-true)
                           (v o 'send)
                           (v o 'WaitforResponse 1000)
                            (e (r (vlax-get-property o 'ResponseText)))
                            (vlax-release-object o)))))
                   (defun-q atlisp-startup ()
                     (if @::init-once
                       (@::init-once)
                       (C:@)))
                   (if (not (listp s::startup)) (setq s::startup nil))
                   (setq s::startup (append s::startup atlisp-startup))
                   (princ)))
              fp-mnl)
            (close fp-mnl))))))
  (if (null (findfile "@lisp.mnu"))
    (progn
      (sleep 3)
      (@::make-menu)
      (prompt "@lisp was installed. Please input @H for help or @T for Tips."))))

;; ── sub-system/help-system.lsp ──────────────────────────────────────────
;; @depends base-function i18n
;; @provides help-system
(defun @::showCopyright()
  "显示版权信息."
  (if (@::internetp)
    (progn
      (@::load-module 'pkgman)
      (@::load-module 'about)
      (@::about))
    (if is-gcad
      (alert
        (strcat " @lisp: "(_ "AutoLisp program manage system.") "      " (_ "Current version")":"  @::version "-" @::*edition* "\n\n"

          "      "
          (_ "@lisp is a autolisp/visuallisp manager running in AutoCAD.")
          "\n\n"
          (_ "Author")":  "
          "(" (cadr (assoc 'nicknameen @::*copyright*)) ")\n"
          (_ "Registration No.")": 2023R11L0750902 \n"
          "QQ Group: 1071980591" "\n"
          "E-mail: " (cadr (assoc 'Email @::*copyright*)) "\n"
          "U  R  I: " (@::uri) "\n\n"
          (_ "Command")":\n"
          " "(_ "Name")"\t"(_ "Mnemonic")"\t "(_ "Description")"\n"
          "  % \t  \t"(_ "Reload.")"\n"
          "  %% \t@panel\t"(_ "Show panel all menu command.")"\n"
          "  %C \tchat\t"(_ "Chat with @lisp aibot.")"\n"
          "  %H \thelp  \t"(_ "Show description and command list.")"\n"
          "  %I \tinstall\t"(_ "Install package.")"\n"
          "  %L \tlist \t"(_ "Show installed packages.")"\n"
          "  %M \tmenu  \t"(_ "Rebuild menu.")"\n"
          "  %P \tpackage \t"(_ "GUI packager manager.")"\n"
          "  %R \tremove\t"(_ "Remove package.")"\n"
          "  %S \tsetup\t"(_ "Setup system configure.")"\n"
          "  %U \tupdate\t"(_ "Update @lisp kernel files and packages in your computer.")"\n"
          "  %W \twww  \t"(_ "Visit @lisp website.")"\n"
      ))
      (alert
        (strcat " @lisp: "(_ "AutoLisp program manage system.") "      "
          (_ "Current version")":"  @::version "-" @::*edition* "\n\n"

          "      "
          (_ "@lisp is a autolisp/visuallisp manager running in AutoCAD.")
          "\n\n"
          (_ "Author")":  "
          "(" (cadr (assoc 'nicknameen @::*copyright*)) ")\n"
          "Registration No.: 2023R11L0750902 \n"
          "QQ Group: 1071980591" "\n"
          "E-mail: " (cadr (assoc 'Email @::*copyright*)) "\n"
          "U  R  I: " (@::uri) "\n\n"
          (_ "Command")":\n"
          " "(_ "Name")"\t"(_ "Mnemonic")"\t "(_ "Description")"\n"
          "  @ \t  \t"(_ "Reload.")"\n"
          "  @@ \t@panel\t"(_ "Show panel all menu command.")" hotkey: F1 \n"
          "  @C \tchat\t"(_ "Chat with @lisp aibot.")"\n"
          "  @H \thelp  \t"(_ "Show description and command list.")"\n"
          "  @I \tinstall\t"(_ "Install package.")"\n"
          "  @L \tlist \t"(_ "Show installed packages.")"\n"
          "  @M \tmenu  \t"(_ "Rebuild menu.")"\n"
          "  @P \tpackage \t"(_ "GUI packager manager.")"\n"
          "  @R \tremove\t"(_ "Remove package.")"\n"
          "  @S \tsetup\t"(_ "Setup system configure.")"\n"
          "  @T \ttips \t"(_ "@lisp Tips.")"\n"
          "  @U \tupdate\t"(_ "Update @lisp kernel files and packages in your computer.")"\n"
          "  @W \twww  \t"(_ "Visit @lisp website.")"\n"
      ))
)))
(defun @::home ()
  (@::open-url @::*prefix*))
(defun @::browser()
  "在线浏览主页"
  (setvar "CMDECHO" 0)
  (@::cmd "start" (@::uri))
  (setvar "cmdecho" 1)
)
(defun @::browser-pkg()
  "在线浏览包列表"
  (setvar "CMDECHO" 0)
  (@::cmd "start" (strcat (@::uri) "/package" ))
  (setvar "cmdecho" 1)
)
(defun @::video-tutorial ()
  (setvar "cmdecho" 0)
  (if (wcmatch @::*locale* "CH*")
    (@::cmd "start" "https://space.bilibili.com/atlisp")
    (@::cmd "start" "https://www.ixigua.com/7151576112680829470?id=7151571133991813668"))
  (setvar "cmdecho" 1)
)
(defun @::reportbug()
  "报告使用中遇到的问题,并提交给软件作者."
  (@::cmd "start" "https://gitee.com/atlisp/service/issues/I5995A")
)
(defun @::set-study-mode()
  (setq @::*study-mode* 10))
(if (null *clipromptlines*)
  (setq *clipromptlines* (getvar "CLIPROMPTLINES")))
(defun @::help (help-str)
  "help info ,need u-s-e-r"
  (if (and (null (@::get-wxid))
      (null @::*help-login-cached*))
    (progn
      (@::@login)
      (setq @::*help-login-cached* t)))
  (if (listp help-str)
    (setq help-str
      (string:from-list
        help-str "\n")))
  (if (member (strcase @::*locale*) '("CHS" "ZH"))
    (cond
      ((> @::*study-mode* 0)
        (@::alert (strcat (_ "Tips:") "\n      " help-str ))
        (setq @::*study-mode* (1- @::*study-mode*)))
      ((= (@::get-config '@::study-mode) 1)
        (if (and (numberp  (@::get-config '@::voice-mode))
            (= 2 (boole 1 2 (fix (@::get-config '@::voice-mode)))))
          (progn
            (@::skip-speak)
            (@::speak help-str)
        ))
        (princ "\n------------------------------\n")
        (princ (strcat (_ "Tips:") "\n      " help-str "\n"))
        (princ "------------------------------\n")
      )
      ((= (@::get-config '@::study-mode) 2)
        (@::alert (strcat (_ "Tips:") "\n      " help-str "\n"))
      )
)))
(defun @::alert (str)
  (if @::*auto-mode*
    (princ str)
    (progn
      (alert (@::speak str))
      (@::skip-speak))
))
(defun @::show-whats-new (new-ver old-ver / changelog)
  "版本升级后显示新功能提示。从网络获取更新日志，比较当前和旧版显示差异。"
  (if (@::internetp)
    (progn
      (setq changelog (@::http-request (strcat (@::uri) "/stable/change.org")))
      (if changelog
        (progn
          (princ "\n========================================\n")
          (princ (strcat "  @lisp " (_ "Upgrade") " " new-ver "\n"))
          (princ "----------------------------------------\n")
          ;; 只显示新版本的变化（从 new-ver 标题到 old-ver 标题之间）
          (setq changelog (@::string-to-list changelog "\n"))
          (setq changelog (member (strcat "* " new-ver) changelog))
          (if changelog
            (progn
              (setq changelog (cdr changelog))
              (setq changelog (reverse (cdr (member (strcat "* " old-ver) (reverse changelog)))))
              (foreach line changelog
                (if (/= "" line)
                  (princ (strcat "  " line "\n"))))))
          (princ "========================================\n"))))))

(defun @::custom-service ()
  (@::alert (_"Efficiency first. If you have customization needs, please contact us via official account, QQ group or customer service."))
  (@::@login)
)


;; ── sub-system/config/store.lsp ──────────────────────────────────────────
;; @depends base-function i18n
;; @provides config-store config-manager
(vl-load-com)
(defun @::define-config (name value description)
  "设置系统及软件包的运行参数。不可重复定义，如已有定义则后定义无效。"
  (if (null (assoc name @::*config-db*))
    (progn
      (setq @::*config-db* (append @::*config-db* (list (cons name (cons value description)))))
      (setq @::*config-default* (append
                                  @::*config-default*
                                  (list (cons name (cons value description))))))
    (@::@log "WARN" (strcat "Config redefined: " (vl-symbol-name name) " by " @::progname))))
(defun @::define-config-typed (name value description type)
  "定义带类型的配置项。type 可为 'int / 'bool / 'str / '(range min max)"
  (@::define-config name value description)
  (setq @::*config-types* (cons (cons name type) @::*config-types*)))
(defun @::define-configs (lst)
  "设置系统及软件包的运行参数。不可重复定义，如已有定义则后定义无效。"
  (if (listp (car lst))
    (foreach cfg lst
      (@::define-config
        (car cfg)
        (cadr cfg)
        (caddr cfg)))
    (@::define-config
      (car lst)
      (cadr lst)
      (caddr lst))))
(defun @::config-validate (name value / type-entry tp minv maxv)
  "校验配置值是否符合类型。返回修正后的值或 nil（拒绝）。"
  (if (setq tp (cdr (assoc name @::*config-types*)))
    (progn
      (cond
        ((eq tp 'int)
         (if (eq 'int (type value))
           value
           (if (and (eq 'str (type value)) (setq value (read value)))
             (if (eq 'int (type value)) value))))
        ((eq tp 'bool)
         (if (member value '(0 1 "0" "1"))
           (if (eq 'str (type value)) (read value) value)))
        ((and (listp tp) (eq 'range (car tp)))
         (setq minv (cadr tp)
               maxv (caddr tp))
         (if (and (member (type value) '(int real)) (>= value minv) (<= value maxv))
           value))
        (t value)))
    value))
(if (null (boundp '@::*config-dirty*))
  (setq @::*config-dirty* nil))
(defun @::save-config ()
  "保存自定义变量。检查脏标志，仅在有更改时写入。"
  (if @::*config-dirty*
    (progn
      (@::save-config-flush)
      (setq @::*config-dirty* nil))))
(defun @::save-config-flush (/ fp opt%)
  "强制将配置写入文件（忽略脏标志）"
  (setq fp (vl-catch-all-apply 'open (list (strcat @::*prefix-config* @::*config-file*) "w")))
  (if (not (vl-catch-all-error-p fp))
    (progn
      (foreach opt% @::*config-db*
        (if
          (and
            (not (listp (cadr opt%)))
            (/=
              (cadr opt%)
              (cadr (assoc (car opt%) @::*config-default*))))
          (progn
            (print
              (list
                (car opt%)
                (cadr opt%))
              fp))))
      (close fp))))
(defun @::set-config (name value / old-value)
  "设置系统及软件包的运行参数。"
  (setq value (@::config-validate name value))
  (if (and value (setq old-value (assoc name @::*config-db*)))
    (setq @::*config-db* (subst
                           (cons name (cons value (cddr old-value)))
                           old-value
                           @::*config-db*))
    (if value
      (setq @::*config-db* (append @::*config-db* (list (cons name (cons value "")))))))
  (if value
    (progn
      (setq @::*config-dirty* t)
      (vl-catch-all-apply (function (lambda () (@::event-emit 'config-changed (list name value)))) nil)
      (vl-catch-all-apply
        (function (lambda ()
           (@::audit-log
             :config.change
             (list
               (cons :target (vl-symbol-name name))
               (cons :value (vl-princ-to-string value))
               (cons :result :success)))))
        nil))))
(defun @::get-config (name)
  "读取设置变量的值。不存在返回 nil。"
  (cadr (assoc name @::*config-db*)))
(defun @::get-config-default (name)
  "读取变量的默认值。"
  (cadr (assoc name @::*config-default*)))
(defun @::get-config-or (name default)
  "读取设置变量的值。不存在时返回 DEFAULT。"
  (if (assoc name @::*config-db*)
    (cadr (assoc name @::*config-db*))
    default))
(defun @::get-config-desc (name)
  "读取设置变量的描述。"
  (cddr (assoc name @::*config-default*)))
(defun @::list-config (/ op%)
  "列设置变量的值。"
  (princ "---------------------------------------\n")
  (foreach op% @::*config-db*
    (princ (_ "Config Item: "))
    (princ (car op%))
    (princ "\n")
    (princ (_ "      Value: "))
    (princ (cadr op%))
    (princ "\n")
    (princ (_ "Description: "))
    (princ (cddr op%))
    (princ "\n")
    (princ "---------------------------------------\n"))
  (princ))
(defun @::load-config (/ opt-new opt-raw line-num)
  "加载自定义变量"
  (setq line-num 0)
  (@::with-file-lines
    (strcat @::*prefix-config* @::*config-file*)
    (function (lambda (opt%)
       (setq line-num (1+ line-num))
       (if
         (and
           opt%
           (/= opt% "")
           (setq opt-new (vl-catch-all-apply 'read (list opt%)))
           (not (vl-catch-all-error-p opt-new))
           (listp opt-new)
           (setq opt-raw (assoc (car opt-new) @::*config-db*)))
         (setq @::*config-db* (subst
                                (cons
                                  (car opt-new)
                                  (cons
                                    (cadr opt-new)
                                    (cddr opt-raw)))
                                opt-raw
                                @::*config-db*))
         (if (and opt% (/= opt% "") (vl-catch-all-error-p opt-new))
           (@::@log "WARN" (strcat "Skipped malformed config line " (itoa line-num) ": " opt%)))))))
  @::*config-db*)


;; ── sub-system/config/migrate.lsp ──────────────────────────────────────────
;; @depends base-function i18n config-store
;; @provides config-migrate
(defun @::profile-dir ()
  "配置模板存放目录"
  (if @::*prefix-config* (strcat @::*prefix-config* "profiles/")))
(defun @::save-config-profile (profile-name / fp dir path)
  "保存当前配置为模板"
  (setq dir (@::profile-dir))
  (vl-mkdir dir)
  (setq path (strcat dir profile-name ".cfg"))
  (setq fp (vl-catch-all-apply 'open (list path "w")))
  (if (and fp (not (vl-catch-all-error-p fp)))
    (progn
      (foreach opt% @::*config-db*
        (if (not (listp (cadr opt%)))
          (print (list (car opt%) (cadr opt%)) fp)))
      (close fp)))
  (@::@log "INFO" (strcat "Config profile saved: " profile-name))
  path)
(defun @::load-config-profile (profile-name / path)
  "加载配置模板"
  (setq path (strcat (@::profile-dir) profile-name ".cfg"))
  (if (findfile path)
    (progn
      (@::with-file-lines
        path
        (function (lambda (opt%)
           (if
             (and
               opt%
               (/= opt% "")
               (setq opt-new (read opt%))
               (setq opt-raw (assoc (car opt-new) @::*config-db*)))
             (setq @::*config-db* (subst
                                    (cons
                                      (car opt-new)
                                      (cons (cadr opt-new) (cddr opt-raw)))
                                    opt-raw
                                    @::*config-db*))))))
      (@::save-config)
      (@::@log "INFO" (strcat "Config profile loaded: " profile-name))
      t)
    (progn
      (@::@log "WARN" (strcat "Config profile not found: " profile-name))
      nil)))
(defun @::list-config-profiles (/ files)
  "列出所有配置模板"
  (setq files (vl-directory-files (@::profile-dir) "*.cfg" 1))
  (mapcar (function (lambda (f) (vl-filename-base f))) files))
(defun @::delete-config-profile (profile-name / path)
  "删除配置模板"
  (setq path (strcat (@::profile-dir) profile-name ".cfg"))
  (if (findfile path)
    (progn
      (vl-file-delete path)
      (@::@log "INFO" (strcat "Config profile deleted: " profile-name))
      t)
    (progn
      (@::@log "WARN" (strcat "Config profile not found: " profile-name))
      nil)))
(defun C:@PROFILE (/ profiles choice)
  "切换配置模板"
  (setq profiles (@::list-config-profiles))
  (if profiles
    (progn
      (foreach p profiles (princ (strcat "\n  " p)))
      (princ (strcat "\n" (_ "Select profile: ")))
      (setq choice (strcase (read-line)))
      (if (member choice profiles)
        (@::load-config-profile choice)
        (princ (strcat "\n" (_ "Profile not found: ") choice))))
    (princ (strcat "\n" (_ "No saved profiles."))))
  (princ))
(defun @::export-config (/ fp)
  "将当前配置导出为 JSON 字符串"
  (setq fp (vl-catch-all-apply 'open (list (strcat @::*prefix* "atlisp-config.json") "w")))
  (if (and fp (not (vl-catch-all-error-p fp)))
    (progn
      (princ "{\n  \"version\": \"" fp)
      (princ @::*version* fp)
      (princ "\",\n  \"config\": [\n" fp)
      (foreach pair @::*config-db*
        (princ
          (strcat
            "    {\"key\": \""
            (vl-symbol-name (car pair))
            "\", \"value\": "
            (@::json-val (cadr pair))
            ", \"desc\": \""
            (cddr pair)
            "\"},\n")
          fp))
      (princ "  ]\n}\n" fp)
      (close fp)
      (strcat @::*prefix* "atlisp-config.json"))))
(defun @::import-config (file / fp content)
  "从 JSON 文件导入配置"
  (setq fp (vl-catch-all-apply 'open (list file "r")))
  (if (and fp (not (vl-catch-all-error-p fp)))
    (progn
      (setq content (read (read-line fp)))
      (close fp)
      (if (listp content)
        (progn
          (foreach pair content
            (@::set-config
              (read (strcat "'" (cdr (assoc :key pair))))
              (read (vl-princ-to-string (cdr (assoc :value pair))))))
          t)
        nil))))
(defun @::json-val (val)
  "将 AutoLISP 值转为 JSON 值字符串"
  (cond
    ((eq 'INT (type val)) (itoa val))
    ((eq 'REAL (type val)) (rtos val 2 6))
    ((eq 'STR (type val)) (strcat "\"" val "\""))
    (t (vl-prin1-to-string val))))


;; ── sub-system/config/dialog.lsp ──────────────────────────────────────────
;; @depends base-function i18n config-store
;; @provides config-dialog
(vl-load-com)
(defun @::edit-config (/ dcl-fp show-lst lst-cfg save-config *error* nop per-page sbarcurr-page sbartotal-page i pattern
                       rd% dcl:accept-hook)
  "编辑配置变量"
  (setq *error* (lambda (msg) (dcl:error msg)))
  "1. Model 建立数据模型。"
  (cond
    ((findfile (strcat @::*prefix* "mini"))
     (setq nop 12))
        ((@::platform-is-linux-p)
     (setq nop 16))
    (t
     (if (< (vlax-get-property *ACAD* 'height) 800)
       (setq nop 12)
       (setq nop 20))))


  (setq per-page nop)
  (if (null per-page) (setq per-page 18))
  (setq sbarcurr-page 0)
  (setq lst-cfg (if @::*config-db*
                  @::*config-db*
                  (@::load-config)))
  (setq sbartotal-page (ceiling (/ (length lst-cfg) (float per-page))))
  "2. View 建立显示视图。"
  (dcl:dialog "editconfig")
  (progn
    (dcl:begin-cluster "row" "")
    (progn
      (write-line
        (strcat
          ":edit_box{key=\"Search\";label=\"Search:\";action=\"(cb-search)\";width=32;fixed_width=true;}"
          ":text{key=\"cp\";value=\"1\";}")
        dcl-fp)
      (dcl:end-cluster))

    (dcl:begin-cluster "row" "")
    (progn
      (write-line
        (strcat
          ":text{value=\"     Option\"; width=32;fixed_width=true;}"
          ":text{value=\"      Value\";width=30;fixed_width=true;}"
          ":text{value=\"      Tips\";width=80;fixed_width=true;}")
        dcl-fp)
      (dcl:end-cluster))
    (dcl:hr 0.17)
    (dcl:begin-cluster "row" "")
    (progn
      (dcl:begin-cluster "column" "")
      (progn
        (setq i -1)
        (repeat per-page
          (dcl:begin-cluster "row" "")
          (progn
            (write-line
              (strcat
                ":text{key=\"rn"
                (itoa (setq i (1+ i)))
                "\"; width=30;fixed_width=true;}"
                ":edit_box{key=\"rv"
                (itoa i)
                "\";width=30;fixed_width=true;}"
                ":text{key=\"rd"
                (itoa i)
                "\";width=80;fixed_width=true;}")
              dcl-fp)
            (dcl:end-cluster))
          (dcl:hr 0.08)))
      (dcl:end-cluster))
    (dcl:scrollbar "sbar" "" nil)
    (dcl:end-cluster)
    (dcl:hr 0.17))
  (dcl:dialog-end-ok-cancel)
  "3. Control 创建控制流程"
  (defun cb-search (/ pattern)
    "search config."
    (setq sbarcurr-page 0)
    (setq pattern (string:subst-all "`@" "@" (get_tile "Search")))
    (setq lst-cfg (vl-remove-if-not
                    (function (lambda (x)
                       (or
                         (wcmatch
                           (strcase (vl-symbol-name (car x)) t)
                           (strcase (strcat "*" pattern "*") t))
                         (wcmatch
                           (strcase (cddr x) t)
                           (strcase (strcat "*" pattern "*") t)))))
                    (if @::*config-db*
                      @::*config-db*
                      (@::load-config))))
    (if (< (length lst-cfg) per-page) (mode_tile "sbar" 1) (mode_tile "sbar" 0))
    (setq @::tmp-search-str nil)
    (if lst-cfg
      (progn
        (setq sbartotal-page (fix (ceiling (/ (length lst-cfg) (float per-page)))))
        (set_tile "sbar" (itoa (1- sbartotal-page)))
        (show-lst))))
  (defun save-config (/ i)
    "save config."
    (setq i 0)
    (repeat per-page
      (if (> (strlen (get_tile (strcat "rn" (itoa i)))) 0)
        (@::set-config
          (read (get_tile (strcat "rn" (itoa i))))
          (@::to-type
            (get_tile (strcat "rv" (itoa i)))
            (type (cadr (assoc (read (get_tile (strcat "rn" (itoa i)))) @::*config-default*))))))
      (setq i (1+ i))))
  (defun cb-sbarscrollbar (key)
    "scroll config."
    (save-config)
    (setq sbarcurr-page (1- (- sbartotal-page (atoi (get_tile key)))))
    (setq sbarcurr-page (max 0 (min sbarcurr-page (1- sbartotal-page))))
    (show-lst))
  (defun show-lst (/ i rd%)
    "show config list."
    (setq i 0)
    (set_tile
      "cp"
      (strcat
        (itoa (1+ sbarcurr-page))
        " / "
        (itoa sbartotal-page)
        " : "
        (itoa (length lst-cfg))))
    (repeat per-page
      (if (nth (+ i (* per-page sbarcurr-page)) lst-cfg)
        (progn
          (set_tile
            (strcat "rn" (itoa i))
            (strcase (vl-symbol-name (car (nth (+ i (* per-page sbarcurr-page)) lst-cfg))) t))
          (set_tile
            (strcat "rv" (itoa i))
            (@::to-string (cadr (nth (+ i (* per-page sbarcurr-page)) lst-cfg))))
          (mode_tile (strcat "rv" (itoa i)) 0)
          (set_tile
            (strcat "rd" (itoa i))
            (progn
              (setq rd% (cddr (nth (+ i (* per-page sbarcurr-page)) lst-cfg)))
              (if (< (@::max-char rd%) 128)
                (_ rd%)
                rd%))))
        (progn
          (set_tile (strcat "rn" (itoa i)) "")
          (set_tile (strcat "rv" (itoa i)) "")
          (mode_tile (strcat "rv" (itoa i)) 1)
          (set_tile (strcat "rd" (itoa i)) "")))
      (setq i (1+ i))))
  "4. New 一个新对话框对象。"
  (dcl:new "editconfig")
  "5. Init 初始化对话框"
  (setq dcl:accept-hook (cons (list "save" 'save-config) dcl:accept-hook))
  (set_tile "title" (_ "Settings"))
  (if (eq 'str (type @::tmp-search-str))
    (progn
      (set_tile "Search" @::tmp-search-str)
      (cb-search))
    (show-lst))
  "6. Show dialog 显示并进行交互"
  (setq @::edit-config-result (if (> (dcl:show) 0) T nil))
  (@::save-config)
  @::edit-config-result)
(defun @::edit-config-dialog ()
  "编辑配置变量"
  (@::edit-config))
(defun @::set-user-info (/ save-user-info successed dcl_id)
  "设置用户信息"
  (defun save-user-info ()
    "save user info."
    (if
      (and
        (member (ascii "@") (vl-string->list (get_tile "email")))
        (= 49 (car (vl-string->list (get_tile "phone"))))
        (>= (apply 'min (vl-string->list (get_tile "phone"))) 48)
        (<= (@::max-char (get_tile "phone")) 57)
        (= 11 (strlen (get_tile "phone"))))
      (progn
        (@::set-config '@::user-email (vl-string-trim " " (get_tile "email")))
        (@::set-config '@::user (vl-string-trim " " (get_tile "username")))
        (@::set-config '@::user-phone (vl-string-trim " " (get_tile "phone")))
        (@::save-config)
        (if
          (or
            (= "" (@::get-config '@::user-email))
            (= "" (@::get-config '@::user))
            (= "anonymous" (@::get-config '@::user))
            (= "" (@::get-config '@::user-phone)))
          (progn
            (alert (_ "Please input information correctly."))
            (setq successed nil))
          (setq successed T)))
      (progn
        (alert (_ "Please input information correctly."))
        (setq successed nil))))
  (if (null (findfile (strcat @::*prefix* "@lisp.dcl")))
    (progn
      (if (null (eq 'subr (type @::down-file)))
        (@::load-module 'pkgman))
      (@::down-file "@lisp.dcl")))
  (setq dcl_id (load_dialog "@lisp.dcl"))
  (if (not (new_dialog "userInfo" dcl_id))
    (progn
      (princ "\n*** @lisp: User info dialog failed to load. ***\n")
      (unload_dialog dcl_id)
      (setq successed nil))
    (progn
      (set_tile "email" (@::get-config '@::user-email))
      (set_tile "username" (@::get-config '@::user))
      (set_tile "phone" (@::get-config '@::user-phone))
      (set_tile "email_desc" (@::get-config-desc '@::user-email))
      (set_tile "user_desc" (@::get-config-desc '@::user))
      (set_tile "phone_desc" (@::get-config-desc '@::user-phone))
      (action_tile "accept" "(save-user-info)(done_dialog)")
      (start_dialog)
      (unload_dialog dcl_id)))
  successed)
(defun @::password-dialog (/ mypasswd set-passwd)
  "设置用户密码,返回经二次变换后的值"
  (defun set-passwd ()
    "set password."
    (setq mypasswd (get_tile "passwd")))
  (defun @::setup-pwd ()
    ""
    (set_tile
      "user"
      (strcat
        (_ "Hello")
        " "
        (@::get-config '@::user)
        ":"))
    (action_tile "accept" "(set-passwd)(done_dialog)"))
  (@::dcl-run-with-setup
    "atlisp-passwd"
    (list
      "password : dialog {label=\"Password\";: column {"
      ":text {label=\"Hello :\";key=\"user\"; }"
      (strcat ": text {label=\"" (_ "Please input your password") ":\";")
      "key=\"label\";}"
      ": edit_box {label=\"Password:\";key=\"passwd\";width=35;password_char = \"*\";fixed_width=true;edit_width=20; alignment=right;action=\"(set-passwd)(done_dialog)\";} ok_cancel; }}")
    "password"
    '@::setup-pwd)
  mypasswd)
(defun C:@S ()
  (@::edit-config-dialog)
  (princ))


;; ── sub-system/ui.lsp ──────────────────────────────────────────
;; @depends base-function config-manager
;; @provides ui
(vl-load-com)
(setq @::*menu*        '()
      @::*devmenu*     '()
      @::*hotkey*      '()
      @::*hotkey-file* "hotkey.cfg")
(if (not (boundp 'flagslow)) (setq flagslow nil))
(defun @::screensize (/ res wmi meth1 meth2)
  "取屏幕分辨率"
  (cond
    ((@::platform-is-linux-p)
     (list (list 1366 768)))
    (t
     (if
       (not
         (vl-catch-all-error-p
           (setq res (vl-catch-all-apply
                        '(lambda (/ wmi meth1 meth2)
                           (setq wmi (vlax-create-object "WbemScripting.SWbemLocator"))
                           (setq meth1 (vlax-invoke-method
                                         wmi
                                         'ConnectServer
                                         nil nil nil nil nil nil nil nil nil))
                           (setq meth2 (vlax-invoke-method
                                         meth1 'ExecQuery
                                         "Select * from Win32_DisplayConfiguration"
                                         nil nil nil))
                           (vlax-for n meth2
                             (setq res (cons
                                         (list
                                           (vlax-get n 'PelsWidth)
                                           (vlax-get n 'PelsHeight))
                                         res)))
                           (vlax-release-object meth2)
                           (vlax-release-object meth1)
                           (vlax-release-object wmi)
                           res)))))
       res
       (list (list 1024 768))))))
(defun @::speak (str / lang gender str-voice async temp-lang temp-gender)
  "语音提示信息"
  (cond
    ((not (@::platform-is-linux-p))
     (if
       (or
         (null @::*speaker*)
         (null (eq 'vla-object (type @::*speaker*)))
         (and
           (eq 'vla-object (type @::*speaker*))
           (vlax-object-released-p @::*speaker*)))
       (if (setq @::*speaker* (vlax-get-or-create-object "Sapi.SpVoice"))
         t
         (@::@log "WARN" "Not found SAPI in your Windows system.")))
     (if
       (and
         (eq 'str (type str))
         @::*speaker*
         (vlax-get-property @::*speaker* 'AudioOutput)
         (vlax-get-property @::*speaker* 'AudioOutputStream)
         (vlax-get-property @::*speaker* 'Voice)
         (vlax-get-property @::*speaker* 'Status))
       (progn
         (setq async (@::get-config '@::speak-asynchronous))
         (vlax-put-property @::*speaker* 'rate (@::get-config '@::speak-rate))
         (vlax-put-property @::*speaker* 'volume (@::get-config '@::speak-volume))

         (if
           (and
             (/= 0 async)
             (/= 1 async))
           (setq async 1))
         (cond
           ((and
              temp-lang
              (member temp-lang '("804" "C04")))
            (setq lang temp-lang))
           ((wcmatch @::*locale* "ch*,zh*")
            (setq lang (if (= 0 (@::get-config '@::speak-voice))
                         "804"
                         "C04")))
           ((wcmatch @::*locale* "jp*")
            (setq lang "411"))
           ((wcmatch @::*locale* "ko*")
            (setq lang "412"))
           ((wcmatch @::*locale* "ru*")
            (setq lang "419"))
           ((wcmatch @::*locale* "PT*")
            (setq lang "416"))
           ((wcmatch @::*locale* "de*")
            (setq lang "407"))
           ((wcmatch @::*locale* "fr*")
            (setq lang "040C"))
           ((wcmatch @::*locale* "IT*")
            (setq lang "410"))
           ((wcmatch @::*locale* "PL*")
            (setq lang "415"))
           (t
            (setq lang "409")))

         (cond
           ((and
              temp-gender
              (member temp-gender '("Male" "Female")))
            (setq gender temp-gender))
           ((member (@::get-config '@::speak-gender) '("Male" "Female"))
            (setq gender (@::get-config '@::speak-gender)))
           (t (setq gender "Female")))

         (setq str-voice   (strcat "<voice required=\"Gender=" gender "\"><lang langid='" lang "'>"
                                   str "</lang></voice>")
               temp-lang   nil
               temp-gender nil)
         (if
           (and
             (eq 'str (type str-voice))
             @::*speaker*)
           (vl-catch-all-error-p
             (vl-catch-all-apply
               'vlax-invoke-method
               (list @::*speaker* "Speak" str-voice async))))))))
  str)
(defun @::skip-speak ()
  "中止语音"
  (while
    (and
      (not (@::platform-is-linux-p))
      @::*speaker*
      (eq 'vla-object (type @::*speaker*))
      (null (vlax-object-released-p @::*speaker*))
      (vlax-get-property @::*speaker* 'AudioOutput)
      (vlax-get-property @::*speaker* 'AudioOutputStream)
      (vlax-get-property @::*speaker* 'Voice)
      (vlax-get-property @::*speaker* 'Status)
      (/= 0 (vlax-invoke @::*speaker* 'skip "Sentence" 5)))
    t))
(defun @::phone ()
  "语音交互-用户说话"
  (if
    (and
      (not (@::platform-is-linux-p))
      (or
        (null @::*phone*)
        (null (eq 'vla-object (type @::*phone*)))
        (and
          (eq 'vla-object (type @::*phone*))
          (vlax-object-released-p @::*phone*))))
    (if (setq @::*phone* (vlax-get-or-create-object "Sapi.SpSharedRecoContext"))
      (progn
        (foreach cmd
          (mapcar
            'car
            (append
              (mapcan 'cdr @::*menu*)
              (mapcan 'cdr (evaltrans @::*menu-man*))
              @::*hidden-voices*))
          (vlax-invoke @::*phone* 'SetAdaptationData cmd))
        t)
      (@::@log "WARN" "Not found SAPI in your Windows system."))))
(defun @::prompt (str)
  "封装prompt"
  (if (listp str)
    (setq str (string:from-list
                str
                "\n")))
  (prompt str)
  (if
    (and
      (numberp (@::get-config '@::voice-mode))
      (= 1 (boole 1 1 (fix (@::get-config '@::voice-mode)))))
    (@::speak str))
  str)
(defun @::gen-voice-cmd (/ fp)
  "语音交互"
  (setq fp (vl-catch-all-apply 'open (list (strcat @::*prefix-config* "voice-cmd.xml") "w")))
  (if (not (vl-catch-all-error-p fp))
    (progn
      (write-line "<?xml version=\"1.0\" encoding=\"gb2312\" ?>" fp)
      (write-line "<GRAMMAR LANGID=\"804\">" fp)
      (write-line "<RULE NAME=\"命令\" TOPLEVEL=\"ACTIVE\">\n<L>" fp)
      (foreach cmd
        (mapcar
          'car
          (append
            (mapcan 'cdr @::*menu*)
            (mapcan 'cdr (evaltrans @::*menu-man*))
            @::*hidden-voices*))
        (write-line (strcat "<P>" cmd "</P>") fp))
      (write-line "</L></RULE></GRAMMAR>" fp)
      (close fp))))


;; ── sub-system/ui/hotkey.lsp ──────────────────────────────────────────
;; @depends base-function
;; @provides ui-hotkey
(defun @::set-hotkey (hotkey mcommand)
  "设置快捷键"
  (if (listp mcommand)
    (setq mcommand (vl-prin1-to-string mcommand)))
  (if (eq 'str (type mcommand))
    (if (atom (read mcommand))
      (setq mcommand (strcat "(vla-sendcommand *DOC* \"" mcommand " \")"))))
  (vl-catch-all-apply '@::safe-eval (list (read (strcat "(defun C:" hotkey " () " mcommand ")")))))
(defun @::define-hotkey (hotkey mcommand)
  "定义热键，当系统中已有定义时，不再重复定义，并给出警告。"
  (if (member hotkey (mapcar (function car) @::*hotkey*))
    (@::alert (strcat (_ "Hotkey ") hotkey " " (_ "is defined")))
    (progn
      (setq @::*hotkey* (append @::*hotkey* (list (cons hotkey mcommand))))
      (@::save-hotkey))))
(defun @::load-hotkey (/ path)
  "加载自定义热键"
  (setq path (if (and @::*prefix-config* @::*hotkey-file*) (strcat @::*prefix-config* @::*hotkey-file*)))
  (if path
    (@::with-file-lines
      path
      (function (lambda (opt%)
         (if (/= opt% "")
           (setq @::*hotkey* (cons (read opt%) @::*hotkey*)))))))
  (mapcar (function (lambda (x) (@::set-hotkey (car x) (cdr x)))) @::*hotkey*))
(defun @::save-hotkey (/ fp opt% path)
  "保存自定义热键"
  (setq path (if (and @::*prefix-config* @::*hotkey-file*) (strcat @::*prefix-config* @::*hotkey-file*)))
  (if path
    (progn
      (setq fp (vl-catch-all-apply 'open (list path "w")))
      (if (and fp (not (vl-catch-all-error-p fp)))
        (progn
          (foreach opt% @::*hotkey*
            (print opt% fp))
          (close fp))))))


;; ── sub-system/ui/menu.lsp ──────────────────────────────────────────
;; @depends base-function config-manager
;; @provides ui-menu
(vl-load-com)
(defun @::add-menu (mclass mname mcommand / mlist)
  "为函数添加CAD菜单项。"
  (if (listp mcommand)
    (setq mcommand (vl-prin1-to-string mcommand)))
  (setq mlist (list mname mcommand (car @::*stack-curr-package*)))
  (if (member mclass (mapcar (function car) @::*menu*))
    (setq @::*menu* (subst
                      (cons
                        mclass
                        (append
                          (cdr (assoc mclass @::*menu*))
                          (list mlist)))
                      (assoc mclass @::*menu*)
                      @::*menu*))
    (setq @::*menu* (append @::*menu* (list (cons mclass (list mlist))))))
  (setq @::*menu* (vl-sort
                    @::*menu*
                    (function
                      (lambda (e1 e2)
                        (< (car e1) (car e2)))))))
(defun @::add-menus (menulist / menu)
  "向系统增加菜单"
  (setq menulist (evaltrans menulist))
  (cond
    ((eq 'str (type (car menulist)))
     (setq menu menulist)
     (if (listp (cadr menu))
       (foreach sub (cdr menu)
         (@::add-menu
           (car menu)
           (car sub)
           (cadr sub)))
       (@::add-menu (car menu) (cadr menu) (caddr menu))))
    ((and (listp (car menulist)) (eq 'str (type (caar menulist))))
     (foreach menu menulist
       (if (listp (cadr menu))
         (foreach sub (cdr menu)
           (@::add-menu
             (car menu)
             (car sub)
             (cadr sub)))
         (@::add-menu (car menu) (cadr menu) (caddr menu)))))))
(defun @::remove-pkg-menu (pkg-name / new-menu category items item)
  "从 @::*menu* 中移除指定包的所有菜单项"
  (setq new-menu nil)
  (foreach category @::*menu*
    (setq items nil)
    (foreach item (cdr category)
      (if (/= (caddr item) pkg-name)
        (setq items (append items (list item)))))
    (if items
      (setq new-menu (append new-menu (list (cons (car category) items))))))
  (setq @::*menu* new-menu))
(defun @::add-devmenu (mclass mname mcommand / mlist)
  "为函数添加CAD菜单项。"
  (setq mlist (list mname mcommand))
  (if (member mclass (mapcar (function car) @::*devmenu*))
    (setq @::*devmenu* (subst
                         (cons
                           mclass
                           (append
                             (cdr (assoc mclass @::*devmenu*))
                             (list mlist)))
                         (assoc mclass @::*devmenu*)
                         @::*devmenu*))
    (setq @::*devmenu* (append @::*devmenu* (list (cons mclass (list mlist))))))
  (setq @::*devmenu* (vl-sort @::*devmenu* (function (lambda (e1 e2) (< (car e1) (car e2)))))))
(setq @::*menu-man* '(((_ "Help")
                        ((_ "@Tips") "(progn(@::load-module 'tips)(@::tips-dialog))")
                        ((_ "Help online") (@::browser))
                        ((_ "Report") (@::reportbug))
                        ((_ "Custom service") (@::custom-service))
                        ("--" "--")
                        ((_ "Study Mode") (@::set-study-mode))
                        ((_ "Video Tutorial") (@::video-tutorial)))
                       ((_ "Config")
                         ((_ "account manage") (@::@login))
                         ((_ "Edit Config") (@::edit-config-dialog))
                         ("--" "--")
                          ((_ "APP manager") (@::package-manager-gui))
                          ((_ "AI CodeGen") (C:@AI))
                         ("--" "--")
                         ((_ "Reload") (progn (load "@lisp") (@::init-once)))
                         ((_ "Update Menu") (@::make-menu))
                         ((_ "Update Locale") (@::update-locale-all))
                         ((_ "Clear MT") (@::clear-mt))
                         ((_ "Upgrade System") (@::upgrade))
                         ("--" "--")
                         ((_ "(@)Home") (@::home))
                         ("--" "--")
                         ((_ "Self destruction") (@::self-destruction)))))
(defun @::package-manager-gui ()
  "包管理面板"
  (@::init-once)
  (if (@::load-module 'pkgman)
    (@::package-manager-dialog)
    (@::@log "WARN" (_ "Network unreachable."))))
(defun @::cmd2str (cmd)
  "命令或表达式转字符串"
  (cond
    ((listp cmd)
     (vl-string-trim " " (vl-prin1-to-string cmd)))
    ((eq 'str (type cmd))
     cmd)
    ((eq 'sym (type cmd))
     (vl-catch-all-apply 'vl-symbol-name (list cmd)))
    (t "(@::about)")))
;; ── CUIX 菜单生成 (ActiveX API) ──────────────────────
(defun @::cuix-find-or-create-group (/ app groups group)
  "查找或创建 @lisp CUIX 菜单组"
  (setq app    (vlax-get-acad-object)
        groups (vla-get-MenuGroups app))
  (vlax-for g groups
    (if (= (strcase (vla-get-Name g)) "@LISP")
      (setq group g)))
  (if (null group)
    (setq group (vlax-invoke groups 'Add "@lisp")))
  group)
(defun @::cuix-add-items (items parent / i macro)
  "向 PopupMenu 添加菜单项列表，支持子菜单和分隔线"
  (setq i 0)
  (foreach item items
    (if (= "--" (car item))
      (vlax-invoke parent 'AddSeparator i)
      (progn
        (setq macro (strcat "^C^C" (@::cmd2str (cadr item)) ";"))
        (vlax-invoke parent 'AddMenuItem i (car item) macro)))
    (setq i (1+ i))))
(defun @::cuix-add-category (category parent / submenu)
  "向父菜单添加一个分类子菜单及其项"
  (setq submenu (vlax-invoke parent 'AddSubMenu 0 (car category)))
  (@::cuix-add-items (cdr category) submenu)
  (vl-catch-all-apply 'vlax-put-property (list submenu 'TagString (car category))))
(defun @::make-menu-cuix (/ group menus menu-bar menu submenu)
  "使用 ActiveX CUIX API 重建 @lisp 菜单"
  (setq group (@::cuix-find-or-create-group))
  (setq menus (vla-get-Menus group))
  (setq menu-bar (vl-catch-all-apply 'vla-get-MenuBar (list group)))
  ;; 从菜单栏移除旧 @lisp 菜单
  (if (not (vl-catch-all-error-p menu-bar))
    (vl-catch-all-apply
      (function (lambda ()
         (vlax-for m menu-bar
           (if (= (strcase (vla-get-Name m)) "@LISP(&A)")
             (vla-RemoveFromMenuBar m)))))
      nil))
  ;; 删除组内旧菜单
  (vl-catch-all-apply
    (function (lambda ()
       (vlax-for m menus
         (vl-catch-all-apply '(lambda () (vlax-invoke m 'Delete)) nil))))
    nil)
  ;; 创建主菜单
  (setq menu (vlax-invoke menus 'Add "@lisp(&A)"))
  ;; 包菜单 @::*menu*
  (if @::*menu*
    (foreach cat @::*menu*
      (@::cuix-add-category cat menu)))
  ;; 固定菜单 @::*menu-man*
  (if @::*menu-man*
    (progn
      (vlax-invoke menu 'AddSeparator 0)
      (foreach cat @::*menu-man*
        (setq submenu (vlax-invoke menu 'AddSubMenu 0 (vl-catch-all-apply '@::safe-eval (list (car cat)))))
        (@::cuix-add-items (cdr cat) submenu))))
  ;; 开发者菜单 @::*devmenu*
  (if @::*devmenu*
    (progn
      (vlax-invoke menu 'AddSeparator 0)
      (foreach cat @::*devmenu*
        (@::cuix-add-category cat menu))))
  ;; 关于
  (vlax-invoke menu 'AddSeparator 0)
  (vlax-invoke
    menu
    'AddMenuItem
    0
    (strcat (_ "About") " @lisp")
    (strcat "^C^C(@::showCopyRight);"))
  ;; 插入到菜单栏
  (if (not (vl-catch-all-error-p menu-bar))
    (vla-InsertInMenuBar menu (1- (max 1 (vla-get-Count menu-bar))))
    (vla-InsertInMenuBar menu 0))
  (if (not is-zwcad) (setvar "menubar" 1))
  (@::@log "INFO" "create @lisp menus (CUIX)"))
(defun @::make-menu (/ menu-file *error*)
  "创建菜单"
  (prompt (_ "根据已安装的功能包生成相关菜单"))
  (setq *error* (lambda (msg) (@::cleanup-dcl msg menu-file nil)))
  (if (and (>= @::*acadver* 18) (null is-zwcad) (null is-gcad))
    (if (vl-catch-all-error-p (vl-catch-all-apply '@::make-menu-cuix nil))
      (progn
        (@::@log "WARN" "CUIX menu creation failed, falling back to .mnu")
        (@::make-menu-mnu))
      (progn
        (if (and (> @::*acadver* 18) (not is-zwcad) (getvar "menubar")) (setvar "menubar" 1))
        (if sidebar:make-menu (sidebar:make-menu))))
    (@::make-menu-mnu)))
(defun @::write-menu-section (items eval-name menu-file / submenu ti% item-name)
  ""
  (foreach menu-item items
    (setq item-name (if eval-name (vl-catch-all-apply '@::safe-eval (list (car menu-item))) (car menu-item)))
    (write-line (strcat "[->" item-name "]") menu-file)
    (setq submenu (cdr menu-item)
          ti%     0)
    (while (< ti% (1- (length submenu)))
      (setq item-name (if eval-name (vl-catch-all-apply '@::safe-eval (list (car (nth ti% submenu)))) (car (nth ti% submenu))))
      (if (= "--" (car (nth ti% submenu)))
        (write-line (strcat "  [" item-name "]") menu-file)
        (write-line
          (strcat
            "  ["
            item-name
            "]^c^c"
            (@::cmd2str (cadr (nth ti% submenu)))
            ";")
          menu-file))
      (setq ti% (1+ ti%)))
    (setq item-name (if eval-name (vl-catch-all-apply '@::safe-eval (list (car (nth ti% submenu)))) (car (nth ti% submenu))))
    (write-line
      (strcat
        "  [<-"
        item-name
        "]^c^c"
        (@::cmd2str (cadr (nth ti% submenu)))
        ";")
      menu-file))
  (write-line "[--]" menu-file))
(defun @::make-menu-mnu (/ menu-file *error* @fp)
  "降级路径：写入 .mnu 文件并加载（旧版 CAD / ZWCAD）"
  (setq *error* (lambda (msg) (@::cleanup-dcl msg menu-file nil)))
  (@::@log "INFO" "create @lisp menus (.mnu)")
  (if (null (findfile (strcat @::*prefix* "@lisp.mnl")))
    (progn
      (setq @fp (vl-catch-all-apply 'open (list (strcat @::*prefix* "@lisp.mnl") "w")))
      (if (not (vl-catch-all-error-p @fp))
        (progn
          (write-line (@::http-request (strcat (@::uri) "/stable/@lisp.mnl")) @fp)
          (close @fp)))))
  (setq menu-file (vl-catch-all-apply 'open (list (strcat @::*prefix* "@lisp.mnu") "w")))
  (if (not (vl-catch-all-error-p menu-file))
    (progn
      (write-line "***MENUGROUP=@LISP" menu-file)
      (write-line "***pop1" menu-file)
      (write-line "**@LISP" menu-file)
      (write-line "[@lisp(&A)]" menu-file)
      (if @::*menu*
        (@::write-menu-section @::*menu* nil menu-file))
      (if @::*menu-man*
        (progn
          (@::load-locale "@lisp")
          (@::write-menu-section @::*menu-man* t menu-file)))
      (if @::*devmenu*
        (@::write-menu-section @::*devmenu* nil menu-file))
      (write-line (strcat "[" (_ "About") " @lisp]^C^C(@::showCopyRight);") menu-file)
      (write-line (strcat "***ACCELERATORS") menu-file)
      (if (= 1 (@::get-config '@::f1))
        (write-line (strcat "[\"F1\"](@::panel-dialog)") menu-file))
      (close menu-file)))
  (sleep 1)
  (setvar "filedia" 0)
  (setvar "cmdecho" 0)
  (if (/= nil (menugroup "@lisp")) (command "menuunload" "@lisp"))
  (cond
    ((and is-gcad (getvar "gcadver")
          (wcmatch (getvar "gcadver") "R*")
          (< (read (substr (getvar "gcadver") 2)) 23.9))
     (if (null (findfile (strcat @::*prefix* "@lisp.CUIX")))
       (@::down-file "@lisp.CUIX"))
     (sleep 3)
     (if (null (findfile "@lisp.CUIX")) (@::fix-path))
     (if (and (findfile (strcat @::*prefix* "@lisp.CUIX")) (null (menugroup "@lisp")))
       (command "menuload" (strcat @::*prefix* "@lisp.CUIX"))))
    ((findfile (strcat @::*prefix* "@lisp.mnu"))
     (command "menuload" "@lisp.mnu"))
    (t (princ "Can NOT create MENU file.")))
  (if (and (> (@::acadver) 18) (not is-zwcad) (getvar "menubar")) (setvar "menubar" 1))
  (setvar "filedia" 1)
  (setvar "cmdecho" 1)
  (if sidebar:make-menu (sidebar:make-menu)))
(defun C:@M ()
  (@::init-once)
  (@::make-menu)
  (princ))
(defun @::self-destruction ()
  "self-destruction"
  (if (= "@LISP" (getstring (@::speak (_ "Please intput '@LISP' to destruct @lisp:"))))
    (progn
      (if (/= nil (menugroup "@lisp"))
        (@::cmd "menuunload" "@lisp"))
      (mapcar
        (function (lambda (x) (vl-file-delete (strcat @::*prefix* x))))
        (vl-directory-files @::*prefix* "@lisp.*"))
      (if (findfile (strcat @::*prefix-config* "pkg-in-use.lst"))
        (vl-file-delete (strcat @::*prefix-config* "pkg-in-use.lst")))
      (if (findfile (strcat @::*prefix-config* "pkg-lock.lst"))
        (vl-file-delete (strcat @::*prefix-config* "pkg-lock.lst")))
      ;; 删除搜索路径
      (if is-gcad
        (if
          (member
            (vl-string-right-trim "\\/" @::*prefix*)
            (@::string-to-list (getenv "GCAD") ";"))
          (setenv
            "GCAD"
            (@::list-to-string
              (vl-remove
                (vl-string-right-trim "\\/" @::*prefix*)
                (@::string-to-list (getenv "GCAD") ";"))
              ";")))
        (if
          (member
            (vl-string-right-trim "\\/" @::*prefix*)
            (@::string-to-list (getenv "ACAD") ";"))
          (setenv
            "ACAD"
            (@::list-to-string
              (vl-remove
                (vl-string-right-trim "\\/" @::*prefix*)
                (@::string-to-list (getenv "ACAD") ";"))
              ";"))))
      (@::alert (@::speak (_ "Uninstall @lisp Completed."))))))


;; ── sub-system/ui/panel.lsp ──────────────────────────────────────────
;; @depends base-function config-manager ui-menu
;; @provides ui-panel
(vl-load-com)
(defun @::panel-button-width (bytelen)
  "计算按钮宽度，按 CAD 平台区分。"
  (fix (max 8 (+ bytelen @::*panel-width-offset*))))
(setq @::*panel-width-offset*
  (cond (is-gcad       4)
        ((< (@::acadver) 22) 7)
        ((= (@::acadver) 22) 2)
        ((> (@::acadver) 22) 4)
        (t               6)))

(defun @::panel-dcl-button (bt-menu bt-width hotkey j% cmd-extractor dcl-fp)
  "生成单个按钮的 DCL 字符串。返回新的 j% 和 hotkey。"
  (if (/= "--" (car bt-menu))
    (write-line (strcat ":button{ fixed_width=true;children_fixed_width=true;children_alignment=left;width="
      (itoa bt-width) ";"
      (if (< (setq hotkey (1+ hotkey)) 91) (strcat "mnemonic=\"" (chr hotkey) "\";") "")
      " key=\"c_" (itoa (setq j% (1+ j%))) "\"; "
      "label=\"" (car bt-menu)
      (if (< hotkey 91) (strcat "(" (chr hotkey) ")") "")
      "\"; action=\"(setq default_cb " (itoa j%)
      ")(run-function \\\"" (apply cmd-extractor (list bt-menu))
      "\\\")\";is_enabled=true;}") dcl-fp))
  (list j% hotkey))

(defun @::panel-dcl-column (menu-column bt-width hotkey j% cmd-extractor max-menus dcl-fp / result)
  "生成一列的 DCL：列头 + 所有按钮 + 填充空白按钮。返回新的 j% 和 hotkey。"
  (write-line (strcat ":column{label=\"" (car menu-column)
    "\";alignment=top;fixed_height=true;fixed_width=true;children_fixed_width=true;width="
    (itoa bt-width) ";") dcl-fp)
  (foreach bt-menu (cdr menu-column)
    (setq result (@::panel-dcl-button bt-menu bt-width hotkey j% cmd-extractor dcl-fp)
          j% (car result) hotkey (cadr result)))
  (repeat (- max-menus (length (vl-remove-if (function (lambda (x) (= "--" (car x)))) (cdr menu-column))))
    (write-line (strcat ":button{ fixed_width=true;children_fixed_width=true; width="
      (itoa bt-width) "; is_enabled=false; }") dcl-fp))
  (write-line "}" dcl-fp)
  (list j% hotkey))

(defun @::panel-dcl-gen (menus-list curr-page per-page hotkey dcl-fp max-menus bytelen bt-width
                          cmd-extractor dialog-title pagenav / bt-menu-column j% c% result)
  "生成命令面板 DCL。返回最后的 j% (按钮计数)。"
  (setq j% 0 c% 0)
  (while (and (< c% per-page) (< c% (- (length menus-list) (* per-page curr-page))))
    (setq bt-menu-column (nth (+ c% (* per-page curr-page)) menus-list))
    (setq bytelen (apply 'max (mapcar (function (lambda (x) (strbytelen (car x)))) (cdr bt-menu-column))))
    (setq bt-width (@::panel-button-width bytelen))
    (if (< hotkey 91) (setq bt-width (+ bt-width 3)))
    (setq result (@::panel-dcl-column bt-menu-column bt-width hotkey j% cmd-extractor max-menus dcl-fp)
          j% (car result) hotkey (cadr result))
    (setq c% (1+ c%)))
  (if pagenav (write-line pagenav dcl-fp))
  j%)

(defun @::panel-dcl-config-buttons (j% max-menus dcl-fp / bt-man bytelen bt-width hotkey)
  "生成配置/帮助按钮列的 DCL。返回 (j% hotkey)。"
  (setq bt-man (vl-remove (last (cdadr @::*menu-man*))
                  (mapcan (function cdr) (reverse @::*menu-man*))))
  (setq bytelen (apply 'max (mapcar (function (lambda (x)
    (strbytelen (if (listp (car x)) (vl-catch-all-apply '@::safe-eval (list (car x))) (car x))))) bt-man)))
  (setq bt-width (@::panel-button-width bytelen))
  (setq hotkey (+ 64 j%))
  (write-line (strcat ":column{label=\"" (_ "Config or Help")
    "\";children_alignment=top;fixed_width=true;children_fixed_width=true;width="
    (itoa bt-width) ";") dcl-fp)
  (foreach bt-menu bt-man
    (if (/= "--" (car bt-menu))
      (write-line (strcat ":button{ fixed_width=true;children_fixed_width=true;children_alignment=left;width="
        (itoa bt-width) ";fixed_height=true;"
        (if (< (setq hotkey (1+ hotkey)) 91) (strcat "mnemonic=\"" (chr hotkey) "\";") "")
        " key=\"c_" (itoa (setq j% (1+ j%))) "\"; "
        "label=\"" (if (listp (car bt-menu)) (vl-catch-all-apply '@::safe-eval (list (car bt-menu))) (car bt-menu))
        (if (< hotkey 91) (strcat "(" (chr hotkey) ")") "")
        "\"; action=\"(run-function \\\""
        (@::string-subst "\\\\\\\"" "\"" (@::cmd2str (cadr bt-menu)))
        "\\\")\";is_enabled=true;}") dcl-fp)))
  (repeat (- max-menus (1+ (length (vl-remove-if (function(lambda (x) (= "--" (car x)))) (cdr bt-man)))))
    (write-line (strcat ":button{ fixed_width=true;children_fixed_width=true; width="
      (itoa bt-width) "; is_enabled=false; }") dcl-fp))
  (write-line "}" dcl-fp)
  (list j% hotkey))

(defun @::panel-after-exec (func nl-str to-list-fn)
  "面板命令执行后的处理：执行函数、NLP 匹配或 AI 聊天。"
  (if func
    (if (eq 'str (type func))
      (if (eq 'list (type (read func)))
        (vl-catch-all-apply '@::safe-eval (list (read func)))
        (if (eq 'subr (vl-catch-all-apply 'type (list (read (strcat "C:" func)))))
          (vl-catch-all-apply (read (strcat "C:" func)) nil)
          (vla-postcommand *DOC* (strcat func (chr 10))))))
    (if (and nl-str (/= "" nl-str))
      (if (setq lst-cmd (@::get-cmd-by-str nl-str))
        (progn
          (setq expr (if (= 1 (length lst-cmd))
                       (cadaar lst-cmd)
                       (ui:button-select (_ "Please select command to run.")
                         (mapcar 'caar lst-cmd))))
          (if expr
            (vla-postcommand *DOC* (strcat (if (eq 'str (type expr)) expr (vl-prin1-to-string expr)) (chr 10)))))
        (if (@::load-module 'nlp)
          (progn
            (@::speak nl-str)
            (setq expr (@nlp::gen-code (@nlp::parse-corpus (apply to-list-fn (list nl-str ";")))))
            (@::@debug "INFO" (vl-prin1-to-string expr))
            (if expr
              (vla-postcommand *DOC* (strcat (if (eq 'str (type expr)) expr (vl-prin1-to-string expr)) (chr 10)))
              (@::panel-ai-fallback nl-str)))
          (@::panel-ai-fallback nl-str))))))

(defun @::panel-ai-fallback (nl-str)
  "NLP 不可用时回退到 AI 聊天。"
  (if (and (null flagslow) (>= (strbytelen nl-str) @::*min-voice-len*))
    (progn
      (@::load-module 'pkgman)
      (@::load-module 'aibot)
      (if @::chat (@::chat nl-str))
      (princ "\n\n>>>>>>>>>>>>>>>>>>"))))

(defun @::panel-setup-callbacks (curr-page per-page total-pages default_cb)
  "设置 DCL 对话框的回调和分页状态。"
  (action_tile "accept" "(done_dialog 1)")
  (action_tile "prev" "(page-up)")
  (action_tile "next" "(page-down)")
  (set_tile "curr_total" (strcat (itoa (1+ curr-page)) "/" (itoa total-pages)))
  (if (= 0 curr-page) (mode_tile "prev" 1) (mode_tile "prev" 0))
  (if (= (1- total-pages) curr-page) (mode_tile "next" 1) (mode_tile "next" 0))
  (if (eq 'int (type default_cb))
    (mode_tile (strcat "c_" (itoa default_cb)) 2)))

(defun @::panel-dcl-header (dialog-title dcl-fp)
  "生成 DCL 对话框头部。"
  (write-line (strcat "panel : dialog {label = \"" dialog-title
    " -> #:" (_ "need internet.") " *:" (_ "under development.")
    "\"; :row{children_alignment=left;:edit_box{label=\""
    (_ "Smart Command") ":\";key=\"cmdstr\";action=\"(eval-cmdstr $value)\";}}"
    ":image{ height=0.1; color=" (itoa theme::*bg-color*)
    "; fixed_height=true;}:row{") dcl-fp))

(defun @::panel-calc-layout (menus-list / bt-man max-menus)
  "计算面板布局参数：最大按钮数、配置按钮列表。返回 (bt-man max-menus)。"
  (setq bt-man (vl-remove (last (cdadr @::*menu-man*))
                  (mapcan (function cdr) (reverse @::*menu-man*))))
  (setq max-menus (max
    (apply 'max (mapcar (function (lambda (x)
      (length (vl-remove-if (function(lambda (x) (= "--" (car x)))) (cdr x))))) menus-list))
    (length (vl-remove-if (function(lambda (x) (= "--" (car x)))) bt-man))))
  (list bt-man max-menus))

(defun @::panel-dcl-footer (total-pages per-page curr-page dcl-fp)
  "生成 DCL 对话框尾部：导航按钮 + 确定/取消。"
  (write-line "}" dcl-fp)
  (write-line (strcat ":image{ height=0.1; color=" (itoa theme::*bg-color*) "; fixed_height=true;}") dcl-fp)
  (if (> total-pages 1)
    (write-line (strcat ":row{alignment=\"centered\";children_alignment=\"centered\";"
      ":button{label=\"(<)" (_ "Prev page") "\";mnemonic=\"<\";key=\"prev\";is_enabled=false;}"
      ":spacer{} :text_part{key=\"curr_total\";alignment=\"centered\";width=10;}"
      ":button{label=\"" (_ "Next page") "(>)\";mnemonic=\">\";key=\"next\";is_enabled=false;}}") dcl-fp))
  (write-line " :spacer {} ok_cancel; }" dcl-fp))

(defun @::panel-dialog-core (menus-list curr-page-key reentry-str dialog-title width-threshold
                             cmd-extractor fallback-func init-module to-list-fn / dcl-fp dcl-tmp
                             dcl_id curr-page per-page after-panel-cmd hotkey
                             page-up page-down *error* nl-str tmp tmp-dbclick-ss lst-cmd expr
                             i% c% j% bt-man max-menus bt-menu-column bytelen bt-width r%
                             layout-info total-pages)
  ""
  (defun *error* (msg)
    (term_dialog)
    (@::*error* msg)
    (if dcl_id (unload_dialog dcl_id))
    (@::cleanup-dcl msg dcl-fp dcl-tmp))
  (@::init-once)
  (if (string-equal
        (setq tmp (l2s (mapcar '- (vl-string->list @::progname) (list 33 58 36 4 39 0))))
        (vl-string-trim ">" (last (@::string-to-list (vl-princ-to-string (vl-catch-all-apply '@::safe-eval (list (read tmp)))) " "))))
    (@::load-module init-module))
  (if tmp-dbclick-ss (progn (sssetfirst nil tmp-dbclick-ss) (setq tmp-dbclick-ss nil)))

  (setq per-page (@::get-config '@::menu-per-page))
  (if (and (not (@::platform-is-linux-p)) (vlax-get-acad-object)
           (< (vlax-get-property (vlax-get-acad-object) 'width) width-threshold))
    (setq per-page (min 6 per-page)))
  (setq curr-page (if (<= (length menus-list) per-page) 0 (@::get-config-or curr-page-key 0))
        total-pages (1+ (/ (1- (length menus-list)) per-page)))
  (defun page-up ()
    (setq curr-page (1- curr-page))
    (@::set-config curr-page-key curr-page)
    (done_dialog 10)
    (setq after-panel-cmd reentry-str))
  (defun page-down ()
    (setq curr-page (1+ curr-page))
    (@::set-config curr-page-key curr-page)
    (done_dialog 10)
    (setq after-panel-cmd reentry-str))
  (defun run-function (func)
    (done_dialog 10)
    (setq after-panel-cmd func))
  (defun eval-cmdstr (cmdstr)
    (if (/= "" cmdstr)
      (progn (done_dialog 10) (setq after-panel-cmd nil nl-str cmdstr))))

  (if (null menus-list)
    (progn
      (@::alert (_ "No package is installed. Please select packages that you needed to install."))
      (fallback-func))
    (progn
      (setq dcl-tmp (if (@::platform-is-linux-p)
                       (strcat @::*tmp-path* "panel.dcl")
                       (vl-filename-mktemp "panel" @::*tmp-path* ".dcl")))
      (setq dcl-fp (vl-catch-all-apply 'open (list dcl-tmp "w")))
      (if (vl-catch-all-error-p dcl-fp)
        (progn (@::alert (_ "Cannot create dialog.")) nil)
        (progn
          (@::panel-dcl-header dialog-title dcl-fp)

          (setq layout-info (@::panel-calc-layout menus-list)
                bt-man (car layout-info)
                max-menus (cadr layout-info))
          (setq hotkey 64)

          (setq j% (@::panel-dcl-gen menus-list curr-page per-page hotkey dcl-fp max-menus nil nil cmd-extractor dialog-title nil))

          (setq j% (@::panel-dcl-config-buttons j% max-menus dcl-fp))

          (@::panel-dcl-footer total-pages per-page curr-page dcl-fp)
          (close dcl-fp)

          (defun @::setup-panel ()
            (@::panel-setup-callbacks curr-page per-page total-pages
              (if (boundp 'default_cb) default_cb nil)))
          (@::dcl-run-file dcl-tmp "panel" '@::setup-panel)
          (@::panel-after-exec after-panel-cmd nl-str to-list-fn))))))

(defun @::panel-dialog ()
  "命令面板"
  (@::panel-dialog-core @::*menu* '@::menu-curr-page "(@::panel-dialog)"
    (_ "Command Panel") 1300
    (function (lambda (bt-menu) (@::string-subst "\\\\\\\"" "\"" (@::cmd2str (cadr bt-menu)))))
    @::allcmd-panel 'network string:to-lst))

(defun @::allcmd-panel ()
  "所有命令面板"
  (@::panel-dialog-core @::*remote-menu* '@::menux-curr-page "(@::allcmd-panel)"
    (strcat "@" (_ "All Command Panel")) 1100
    (function (lambda (bt-menu)
       (@::string-subst "\\\\\\\"" "\""
         (car (string:to-list (string:subst-all "" " " (car bt-menu)) (chr 40))))))
    @::package-manager-gui 'pkgman string:to-list))

(if is-gcad
  (progn
    (defun C:% () (C:@))
    (defun C:%% () (C:@@))
    (foreach cmd '("1" "AI" "BATCH" "C" "CN" "D" "DEP" "DIAG" "DGN"
                   "F" "G" "H" "I" "K" "L" "LOCK" "LOGIN"
                   "M" "MCP" "P" "PROFILE" "R" "S" "SYNC"
                   "T" "U" "UNLOCK" "UPGRADE" "V" "VOICE"
                   "W" "WELCOME" "X" "@W" "agent")
      (vl-catch-all-apply '@::safe-eval (list (list 'defun (read (strcat "C:%" cmd)) nil
                  (list (read (strcat "C:@" cmd))) '(princ)))))))


;; ── sub-system/voice.lsp ──────────────────────────────────────────
;; @depends base-function
;; @provides voice
(vl-load-com)
(setq @::*hidden-voices*
  '(("命令面板" "(C:@@)")
))
(defun @::voice-status (/ output status)
  (if (and @::*speaker*
      (eq 'vla-object (type @::*speaker*))
      (null (vlax-object-released-p @::*speaker*)))
    (progn
      (setq status (vlax-get-property @::*speaker* 'Status))
      (if status
        (setq output
          (cond
            ((= 0 (vlax-get-property status 'RunningState)) (_ "idle"))
            ((= 1 (vlax-get-property status 'RunningState)) (_ "speaking"))
            ((= 2 (vlax-get-property status 'RunningState)) (_ "paused"))
            (t (_ "unknown")))))
      (setq output (strcat output " | "
          (vlax-get-property (vlax-get-property @::*speaker* 'Voice) 'GetDescription))))
    (setq output (_ "Voice not initialized")))
  output)
(defun @::voice-list-voices (/ voices i count token desc result buf)
  (setq buf nil)
  (if (and (not (@::platform-is-linux-p))
      (setq voices (vlax-get-or-create-object "Sapi.SpVoice")))
    (progn
      (setq count (vlax-get (vlax-get-property voices 'GetVoices) 'Count))
      (setq i 0)
      (repeat count
        (setq token (vlax-invoke (vlax-get-property voices 'GetVoices) 'Item i))
        (setq desc (vlax-get-property token 'GetDescription))
        (setq buf (cons (strcat (itoa (1+ i)) ". " desc "\n") buf))
        (setq i (1+ i)))
      (vlax-release-object voices)
      (setq result (apply 'strcat (reverse buf))))
    (setq result (_ "Voice system not available on this platform.")))
  (if (= 0 (strlen result))
    (setq result (_ "No voices found.")))
  result)
(defun @::voice-stop ()
  (if (and @::*speaker*
      (eq 'vla-object (type @::*speaker*))
      (null (vlax-object-released-p @::*speaker*)))
    (vlax-invoke @::*speaker* 'skip "Sentence" 100))
  t)
(defun @::voice-test (/ msg)
  (setq msg (strcat (_ "@lisp Voice Test")
      "\n" (_ "Status: ") (@::voice-status)
      "\n" (_ "Rate: ") (itoa (@::get-config '@::speak-rate))
      "\n" (_ "Volume: ") (itoa (@::get-config '@::speak-volume))
      "\n" (_ "Gender: ") (@::get-config '@::speak-gender)))
  (@::alert msg)
  (@::speak (_ "This is a voice test for @lisp system. If you hear this, the voice system is working correctly."))
  msg)
(defun C:@VOICE (/ choice)
  (princ (strcat "\n@lisp: " (_ "Voice System")))
  (princ (strcat "\n  " (_ "Status: ") (@::voice-status)))
  (princ (strcat "\n  1. " (_ "Test voice")))
  (princ (strcat "\n  2. " (_ "List available voices")))
  (princ (strcat "\n  3. " (_ "Stop speaking")))
  (princ (strcat "\n  " (_ "Select: ")))
  (setq choice (strcase (read-line)))
  (cond
    ((= choice "1") (@::voice-test))
    ((= choice "2") (@::alert (@::voice-list-voices)))
    ((= choice "3") (@::voice-stop) (princ (strcat "\n@lisp: " (_ "Voice stopped.")))))
  (princ))


;; ── sub-system/package/lifecycle.lsp ──────────────────────────────────────────
;; @depends base-function
;; @provides package-lifecycle
(vl-load-com)
(@::handle-keywords
  '(:name :full-name :author :version :email :description :category :required :url :files
          :compatible :required :machineid :msg :token :result :i18n :eval-code :opensource :free))
(setq @::*pkg-lifecycle-hooks* nil)
(defun @::pkg-on-load (pkg-name hook-fn)
  "注册包加载回调。包加载完成时调用 hook-fn"
  (setq @::*pkg-lifecycle-hooks* (cons
                                   (list pkg-name 'on-load hook-fn)
                                   @::*pkg-lifecycle-hooks*))
  hook-fn)
(defun @::pkg-on-unload (pkg-name hook-fn)
  "注册包卸载回调。包卸载前调用 hook-fn"
  (setq @::*pkg-lifecycle-hooks* (cons
                                   (list pkg-name 'on-unload hook-fn)
                                   @::*pkg-lifecycle-hooks*))
  hook-fn)
(defun @::pkg-clear-hooks (pkg-name)
  "清除指定包的所有生命周期钩子"
  (setq @::*pkg-lifecycle-hooks* (vl-remove-if
                                   (function (lambda (h) (= (car h) pkg-name)))
                                   @::*pkg-lifecycle-hooks*)))
(defun @::pkg-fire-hooks (pkg-name hook-type)
  "触发指定包和钩子类型的所有回调"
  (foreach h @::*pkg-lifecycle-hooks*
    (if
      (and
        (= (car h) pkg-name)
        (= (cadr h) hook-type))
      (vl-catch-all-apply (caddr h) nil))))
(defun @::def-pkg (pkg-info)
  "定义包信息，将信息载入包列表 *local-pkgs* "
  (if (null (member (@::pkg pkg-info :name) (mapcar 'car @::*local-pkgs*)))
    (setq @::*local-pkgs* (append @::*local-pkgs* (list (cons (@::pkg pkg-info :name) pkg-info))))
    ;; 替换信息
    (setq @::*local-pkgs* (subst
                            (cons (@::pkg pkg-info :name) pkg-info)
                            (assoc (@::pkg pkg-info :name) @::*local-pkgs*)
                            @::*local-pkgs*)))
  @::*local-pkgs*)
(defun @::get-pkg-deps (pkg-info / deps)
  "获取包的所有依赖（合并 :required 和 :depends-on）"
  (setq deps (@::pkg pkg-info :required))
  (if (null (eq 'LIST (type-of deps))) (setq deps (list deps)))
  (if (@::pkg pkg-info :depends-on)
    (setq deps (append
                 deps
                 (if (eq 'LIST (type-of (@::pkg pkg-info :depends-on)))
                   (@::pkg pkg-info :depends-on)
                   (list (@::pkg pkg-info :depends-on))))))
  (vl-remove nil deps))
(defun @::mark-pkg-loaded (pkg-name)
  "标记包为已加载状态，更新包栈、包状态和已用列表"
  (setq @::*stack-curr-package* (cdr @::*stack-curr-package*))
  (setq @::*pkg-state* (append @::*pkg-state* (list pkg-name)))
  (if (null (member pkg-name @::*pkg-in-use*))
    (setq @::*pkg-in-use* (append @::*pkg-in-use* (list pkg-name))))
  (@::save-pkg-in-use)
  (@::pkg-fire-hooks pkg-name 'on-load))


;; ── sub-system/package/lock.lsp ──────────────────────────────────────────
;; @depends base-function
;; @provides package-lock
(vl-load-com)
;; ── 多实例文件锁 ──────────────────────────────────────
(defun @::lock-try (/ fp now file-time locked)
  "尝试获取文件锁 ~/.atlisp/.lock。返回 T 成功，nil 被占用"
  (if (null @::*prefix-config*) nil
    (progn
      (setq now    (* @::*seconds-per-day* (getvar "date"))
            locked nil)
      (while (and (null locked) (findfile (strcat @::*prefix-config* ".lock")))
    (setq fp (vl-catch-all-apply 'open (list (strcat @::*prefix-config* ".lock") "r")))
    (if (not (vl-catch-all-error-p fp))
      (progn
        (setq file-time (atof (read-line fp)))
        (close fp))
      (setq file-time 0))
    (if (> (- now file-time) 30)
      (vl-file-delete (strcat @::*prefix-config* ".lock"))
      (setq locked 'busy)))
  (if (null locked)
    (progn
      (setq fp (vl-catch-all-apply 'open (list (strcat @::*prefix-config* ".lock") "w")))
      (if (not (vl-catch-all-error-p fp))
        (progn
          (write-line (rtos now 2 6) fp)
          (close fp)
          t)
        nil))
    nil))))
(defun @::lock-release ()
  "释放文件锁"
  (if (and @::*prefix-config* (findfile (strcat @::*prefix-config* ".lock")))
    (vl-file-delete (strcat @::*prefix-config* ".lock"))))
(defun @::save-pkg-lock-states (/ fp)
  "持久化包锁定状态列表到磁盘"
  (if (and @::*pkg-lock* @::*prefix-config*)
    (if (@::lock-try)
      (progn
        (setq fp (vl-catch-all-apply
                   'open
                   (list (strcat @::*prefix-config* "lock-states.lst") "w")))
        (if (not (vl-catch-all-error-p fp))
          (progn
            (foreach pkg-name @::*pkg-lock*
              (write-line pkg-name fp))
            (close fp)))
        (@::lock-release))
      (@::@log "WARN" "Save lock-states.lst skipped: another CAD instance is writing."))))
(defun @::load-pkg-lock-states (/ fp pkg-name)
  "从磁盘加载包锁定状态列表"
  (setq @::*pkg-lock* nil)
  (if (and @::*prefix-config* (findfile (strcat @::*prefix-config* "lock-states.lst")))
    (progn
      (setq fp (open (strcat @::*prefix-config* "lock-states.lst") "r"))
      (while (setq pkg-name (read-line fp))
        (if (/= "" pkg-name)
          (setq @::*pkg-lock* (cons pkg-name @::*pkg-lock*))))
      (close fp))))
(defun @::load-pkg-lock (/ fp line pos name ver-str pkgs)
  "载入包锁信息。如果 @::*pkg-in-use* 已加载则直接复用，否则读文件。"
  (if @::*pkg-in-use*
    (mapcar (function (lambda (p) (cons p "?"))) @::*pkg-in-use*)
    (progn
      (if (and @::*prefix-config* (findfile (strcat @::*prefix-config* "pkg-in-use.lst")))
        (progn
          (setq fp (open (strcat @::*prefix-config* "pkg-in-use.lst") "r"))
          (while (setq line (read-line fp))
            (setq pos (vl-string-search " " line))
            (if pos
              (progn
                (setq name (substr line 1 pos))
                (setq ver-str (substr line (+ pos 2)))
                (setq pkgs (cons (cons name ver-str) pkgs)))))
          (close fp)))
      (if (null pkgs)
        (if (and @::*prefix-config* (findfile (strcat @::*prefix-config* "pkg-lock.lst")))
          (progn
            (setq fp (open (strcat @::*prefix-config* "pkg-lock.lst") "r"))
            (while (setq line (read-line fp))
              (setq pos (vl-string-search " " line))
              (if pos
                (progn
                  (setq name (substr line 1 pos))
                  (setq ver-str (substr line (+ pos 2)))
                  (setq pkgs (cons (cons name ver-str) pkgs)))))
            (close fp))))
      pkgs)))
(defun @::pkg-lock-check (/ locked mismatch pkg-name info)
  "检查当前包状态是否与锁文件一致，缺失包自动安装"
  (setq locked (@::load-pkg-lock))
  (if locked
    (progn
      (foreach l locked
        (setq pkg-name (car l)
              info (cdr (assoc pkg-name @::*local-pkgs*)))
        (if info
          (if (and (cdr l) (/= (cdr l) "?") (/= (cdr l) (@::pkg info :version)))
            (progn
              (@::@log
                "WARN"
                (strcat
                  "Package "
                  pkg-name
                  " version mismatch: lock="
                  (cdr l)
                  " installed="
                  (@::pkg info :version)))
              (setq mismatch t)))
          (progn
            (@::@log "INFO" (strcat "Package " pkg-name " not installed, auto installing ..."))
            (@::load-module 'pkgman)
            (if (and (boundp '@::package-install-force) (@::package-install-force pkg-name))
              (setq @::*pkg-state* (cons pkg-name @::*pkg-state*))
              (progn
                (@::@log "WARN" (strcat "Auto install " pkg-name " failed"))
                (setq mismatch t))))))
      (if mismatch
        (princ (strcat "\n@lisp: " (_ "Package lock mismatch detected. Run C:@UPGRADE to sync."))))
      (not mismatch))
    t))
(defun C:@LOCK (/ pkg-name)
  "锁定包，禁止升级/卸载"
  (setq pkg-name (getstring (_ "Please input the package name that you will lock: ")))
  (if
    (and
      (/= "" (strlen pkg-name))
      (member pkg-name (mapcar 'car @::*local-pkgs*)))
    (progn
      (setq @::*pkg-lock* (cons pkg-name @::*pkg-lock*))
      (@::save-pkg-lock-states)
      (@::@log "INFO" (strcat (_ "Locked") " " pkg-name)))
    (@::@log "WARN" (strcat "Package " pkg-name " not found"))))
(defun C:@UNLOCK (/ pkg-name)
  "解锁包，允许升级/卸载"
  (setq pkg-name (getstring (_ "Please input the package name that you will unlock: ")))
  (if
    (and
      (/= "" (strlen pkg-name))
      (member pkg-name @::*pkg-lock*))
    (progn
      (setq @::*pkg-lock* (vl-remove pkg-name @::*pkg-lock*))
      (@::save-pkg-lock-states)
      (@::@log "INFO" (strcat (_ "Unlocked") " " pkg-name)))
    (@::@log "WARN" (strcat "Package " pkg-name " not locked")))
  (princ))


;; ── sub-system/package/persist.lsp ──────────────────────────────────────────
;; @depends base-function package-lifecycle
;; @provides package-persist
(vl-load-com)
(defun @::sort-pkg-in-use (/ t%)
  "计算依赖关系并排序。"
  (vl-remove
    nil
    (vl-sort
      @::*pkg-in-use*
      (function
        (lambda (e1 e2)
          (setq t% (@::get-pkg-deps (cdr (assoc e1 @::*local-pkgs*))))
          (if (null (eq 'LIST (type-of t%))) (setq t% (list t%)))
          (if (member e2 t%)
            nil
            T))))))
;; 将当前系统中运行的包列表写入持久文本。
(defun @::save-pkg-in-use (/ inst-fp info pkgs)
  "保存安装的包列表（含版本号）"
  (if (@::lock-try)
    (progn
      (setq pkgs (@::sort-pkg-in-use))
      (if (and pkgs @::*prefix-config*)
        (progn
          (setq inst-fp (vl-catch-all-apply
                          'open
                          (list (strcat @::*prefix-config* "pkg-in-use.lst") "w")))
          (if (not (vl-catch-all-error-p inst-fp))
            (progn
              (foreach pkg-name pkgs
                (setq info (cdr (assoc pkg-name @::*local-pkgs*)))
                (write-line (strcat pkg-name " " (if info (@::pkg info :version) "?")) inst-fp))
              (close inst-fp)))))
      (if (findfile (strcat @::*prefix-config* "pkg-lock.lst"))
        (vl-file-delete (strcat @::*prefix-config* "pkg-lock.lst")))
      (@::lock-release))
    (@::@log "WARN" "Save pkg-in-use.lst skipped: another CAD instance is writing.")))
;;  取包信息中的选项内容
(defun @::pkg (pkg-info att  / result)
  "取包信息属性内容。"
  (setq result (cdr (assoc att pkg-info)))
  (if (atom result)
    result
    (if
      (and
        (eq 'list (type-of result))
        (= 1 (length result))
        (/= att ':files))
      (car result)
      result)))
(defun @::get-local-pkg-info (pkg-name / result pkg-lsp-path pkg-file)
  ""
  (if (null pkg-name) (setq pkg-name ""))
  (if (eq 'sym (type pkg-name)) (setq pkg-name (strcase (vl-symbol-name pkg-name) t)))
  (setq pkg-lsp-path (strcat "packages/" pkg-name "/pkg.lsp")
        pkg-file     (findfile (strcat "packages/" pkg-name "/pkg.lsp"))
        result       (if pkg-file
                       (if (= "failure" (load pkg-file "failure"))
                         (progn
                           (vl-file-delete pkg-file)
                           nil)
                         (cdr (assoc pkg-name @::*local-pkgs*)))
                       (cdr (assoc pkg-name @::*local-pkgs*))))
  result)
;; 如果是可执行 lsp/fas 文件 则加扩展名。
(defun @::pkg-fas-file (file)
  "下载包文件"
  (cond
    ((null file) nil)
    ((= (vl-filename-extension file) nil) (strcat file fasext))
    (t file)))
(defun @::pkg-lsp-file (file)
  "下载包文件"
  (cond
    ((null file) nil)
    ((= (vl-filename-extension file) nil) (strcat file ".lsp"))
    (t file)))
(defun @::package-path (pkg-name)
  ""
  (if (eq 'sym (type pkg-name)) (setq pkg-name (strcase (vl-symbol-name pkg-name) t)))
  (@::path-os (strcat @::*prefix* "packages/" pkg-name "/")))
;; 列本地包
(defun @::package-list-local (/ pkg-info lines%)
  "列本地 CAD 工具包"
  (setq lines% (list (strcat (_ "Local packages:") "\n========================\n")))
  (foreach pkg-info (mapcar 'cdr @::*local-pkgs*)
    (setq lines% (cons (strcat "Name: " (@::pkg pkg-info :name) "\n") lines%))
    (if (@::pkg pkg-info :full-name)
      (setq lines% (cons (strcat "Full Name: " (_ (@::pkg pkg-info :full-name)) "\n") lines%)))
    (setq lines% (cons (strcat "Author : " (@::pkg pkg-info :author) "\n") lines%))
    (setq lines% (cons (strcat "Version: " (@::pkg pkg-info :version) "\n") lines%))
    (setq lines% (cons (strcat "Description: " (_ (@::pkg pkg-info :description)) "\n") lines%))
    (setq lines% (cons (strcat "--------------------------------------------\n") lines%)))
  (setq lines% (cons (strcat "   " (itoa (length @::*local-pkgs*)) " local packages.\n\n") lines%))
  (setq lines% (apply 'strcat (reverse lines%)))
  (if (> (length @::*local-pkgs*) 5)
    (progn
      (princ lines%)
      (textpage))
    (@::alert lines%))
  (princ))
;; 列本地存在的包。
(defun @::package-list-in-local (/ pkg%)
  "列已本地存在的应用包"
  (foreach pkg% (vl-directory-files (strcat @::*prefix* "packages/") nil -1)
    (if
      (and
        (/= "." pkg%)
        (/= ".." pkg%)
        (findfile (strcat "packages/" pkg% "/pkg.lsp")))
      (@::@load (strcat pkg% "/pkg"))))
  @::*local-pkgs*)
(defun sort-by-fullname (pkgs-list)
  ""
  (vl-sort
    pkgs-list
    (function (lambda (e1 e2) (< (cdr (assoc :full-name e1)) (cdr (assoc :full-name e2)))))))

;; ── sub-system/package/load.lsp ──────────────────────────────────────────
;; @depends base-function net package-lifecycle package-persist
;; @provides package-load
(vl-load-com)
(defun @::test-zip (file / *error*)
  "测试 zip 文件完整性"
  (setq *error* (@::error-handler nil))
  (if (null (findfile "bin/unzip.exe"))
    (progn
      (if (null (eq 'subr (type @::down-file)))
        (@::load-module 'pkgman))
      (@::down-file "bin/unzip.exe")
      (sleep 3)))
  (vl-file-delete (strcat @::*tmp-path* "testzip"))
  (if (findfile "bin/unzip.exe")
    (progn
      (or
        @::*enable-start*
        (@::check-pgp)
        (@::patch-pgp))
      (setvar "cmdecho" 0)
      (@::cmd
        "start-bg"
        (strcat
          " /D \""
          (@::shell-escape @::*prefix*)
          "\" /MIN /B  "
          "bin\\unzip -t "
          (@::shell-escape (@::path-win-format (strcat @::*prefix* file)))
          " > "
          (@::shell-escape @::*tmp-path*)
          "testzip"))
      (sleep 1)
      (=
        "No errors"
        (substr
          (last
            (@::string-to-list
              (@::get-file-contents (strcat @::*tmp-path* "testzip"))
              "\n"))
          1
          9))
      (setvar "cmdecho" 1))
    (@::alert (_ "Can not download unzip file. Please CHECK and close antivirus program. e.g 360."))))
(defun @::unzip (file dir / *error*)
  "解压文件到目录"
  (setq *error* (@::error-handler nil))
  (if (null (findfile "bin/unzip.exe"))
    (progn
      (if (null (eq 'subr (type @::down-file)))
        (@::load-module 'pkgman))
      (@::down-file "bin/unzip.exe")
      (sleep 3)))
  (@::ensure-start-enabled)
  (setvar "cmdecho" 0)
  (@::cmd
    "start-bg"
    (strcat
      " /D \""
      (@::shell-escape @::*prefix*)
      "\" /MIN /B  "
      "bin\\unzip -o "
      (@::shell-escape (@::path-win-format (findfile file)))
      " -d "
      (@::shell-escape (@::path-win-format (strcat @::*prefix* dir)))
      " > "
      (@::shell-escape @::*tmp-path*)
      "unzip-file"))
  (setvar "cmdecho" 1)
  (sleep 1))
(defun @::zip (dir file / *error*)
  "压缩目录到文件"
  (setq *error* (@::error-handler nil))
  (or
    @::*enable-start*
    (@::check-pgp)
    (@::patch-pgp))
  (@::cmd
    "powershell-bg"
    (strcat
      "Compress-Archive -Path '"
      (@::shell-escape (@::path-win-format dir))
      "' -DestinationPath '"
      (@::shell-escape (@::path-win-format file))
      "'")))
(defun @::load-local-file (lspfile / path-fas path-lsp result)
  ""
  (if
    (or
      (null (vl-filename-extension lspfile))
      (= (vl-filename-extension lspfile) (strcat "." @::*lang*)))
    (progn
      (setq path-fas (strcat "packages/" lspfile fasext)
            path-lsp (strcat "packages/" lspfile ".lsp"))
      (cond
        ((and
           (findfile path-fas)
           (setq result (load (strcat "packages/" lspfile) "failure"))
           (/= result "failure"))
         (@::@debug "INFO" (strcat "load fas " lspfile))
         t)
        ((and
           (findfile path-lsp)
           (setq result (load (strcat "packages/" lspfile ".lsp") "failure"))
           (/= result "failure"))
         (@::@debug "INFO" (strcat "load lsp " lspfile))
         t)
        (t nil)))
    nil))
(defun @::download-and-load (lspfile)
  ""
  (setq @::*flag-damage* 1)
  (if (@::internetp)
    (progn
      (if (null (member 'pkgman @::*modules*))
        (@::load-module 'pkgman))
      (if (= "" (vl-filename-directory lspfile))
        (@::download-simple-file lspfile)
        (@::download-pkg-subfile lspfile)))
    (@::@log "ERROR" (strcat (_ "Can not find fas/lsp file: ") lspfile))))
(defun @::download-simple-file (lspfile)
  ""
  (if (member (vl-filename-base lspfile) '("version"))
    (@::down-file (strcat lspfile ".lsp"))
    (progn
      (@::down-file (strcat lspfile fasext))
      (if (null (findfile (strcat "packages/" lspfile fasext)))
        (@::down-file (strcat lspfile ".lsp"))))))
(defun @::download-pkg-subfile (lspfile / edition uri)
  ""
  (setq edition (@::get-remote-pkg-edition (vl-filename-directory lspfile))
        uri     (@::uri))
  (if (member (vl-filename-base lspfile) '("pkg"))
    (@::down-pkg-file uri (strcat lspfile ".lsp") edition)
    (progn
      (@::down-pkg-file uri (strcat lspfile fasext) edition)
      (if (null (findfile (strcat "packages/" lspfile fasext)))
        (@::down-pkg-file uri (strcat lspfile ".lsp") edition)))))
(defun @::@load (lspfile / *error*)
  "加载 .fas 文件,如果没有 .fas 则加载 .lsp,如果没有则提示没有,参数不带扩展名。"
  (setq *error* (@::load-error-handler lspfile))
  (cond
    ((not @::*dev-mode*)
     (if (not (@::load-local-file lspfile))
       (@::download-and-load lspfile)))
    (@::*dev-mode*
     (if (findfile (strcat "packages/" lspfile ".lsp"))
       (if (= "failure" (load (strcat "packages/" lspfile ".lsp") "failure"))
         (@::@log "ERROR" (strcat (_ "load ") lspfile (_ " failure."))))
       (if (findfile (strcat "packages/" lspfile fasext))
         (if (= "failure" (load (strcat "packages/" lspfile) "failure"))
           (@::@log "ERROR" (strcat (_ "load ") lspfile (_ "failure."))))
         (@::@log "ERROR" (strcat (_ "Can not find lsp/fas file: ") lspfile)))))))
(defun @::load-error-handler (lspfile)
  ""
  (lambda (msg / fp)
    (setq fp (findfile (strcat "packages/" lspfile fasext)))
    (if fp (vl-file-delete fp))
    (if (boundp '@::*error*) (@::*error* msg))
    (@::@log "ERROR" (strcat "in file packages/" lspfile))
    (princ (strcat "\n" (_ "Please input @ to reload @lisp. And try to fix me.")))
    (princ)))
(defun @::resolve-single-dep (dep-str seen / dep-name con tmp)
  ""
  (setq dep-name (car (@::parse-version-constraint dep-str))
        con      (cdr (@::parse-version-constraint dep-str)))
  (if (and (cadr con) (car con))
    (progn
      (setq tmp (@::pkg (@::get-local-pkg-info dep-name) :version))
      (if (and tmp (not (@::version-satisfies-p tmp con)))
        (@::@log "WARN" (strcat dep-name " version " tmp " does not satisfy " dep-str)))))
  (@::load-pkg dep-name seen))
(defun @::resolve-list-deps (deps-list seen / dep-name con tmp pkg%)
  ""
  (foreach pkg% deps-list
    (setq dep-name (car (@::parse-version-constraint pkg%))
          con      (cdr (@::parse-version-constraint pkg%)))
    (if (and (cadr con) (car con))
      (progn
        (setq tmp (@::pkg (@::get-local-pkg-info dep-name) :version))
        (if (and tmp (not (@::version-satisfies-p tmp con)))
          (@::@log "WARN" (strcat dep-name " version " tmp " does not satisfy " pkg%)))))
    (@::load-pkg dep-name seen)))
(defun @::load-pkg-files (pkg-name)
  ""
  (cond
    ((= "zh_CN" @::*lang*)
     (@::@load (strcat pkg-name "/" pkg-name "-whole")))
    ((= "zh_TW" @::*lang*)
     (@::@load (strcat pkg-name "/" pkg-name "-whole." @::*lang*)))
    (t
     (@::@load (strcat pkg-name "/" pkg-name "-whole"))))
  (if (findfile (strcat (@::package-path pkg-name) "hotkey.lsp"))
    (load (strcat "packages/" pkg-name "/hotkey.lsp") "failure")))
(defun @::handle-incompatible-pkg (pkg-name)
  ""
  (@::load-module 'pkgman)
  (@::package-update)
  (sleep 1)
  (if (@::package-install-sub pkg-name)
    (progn
      (@::@log "INFO" (strcat "Install " pkg-name " succeeded."))
      t)
    (progn
      (@::@log "ERROR" (strcat (_ "Can not find package in local or server: ") pkg-name))
      (print (_ "System maintenance, upgrade suspended. Please try again later."))
      nil)))
(defun @::load-pkg (pkg-name seen / catch-result%)
  "加载包，加载前检查完整性。seen 用于检测循环依赖。"
  (if (eq 'sym (type pkg-name)) (setq pkg-name (strcase (vl-symbol-name pkg-name) t)))
  (if (member pkg-name seen)
    (progn
      (@::@log "WARN" (strcat "Circular dependency detected: " pkg-name))
      nil)
    (progn
      (setq seen (cons pkg-name seen))
      (setq catch-result% (vl-catch-all-apply
                            (function
                              (lambda (/ required%)
                                (if (null (member pkg-name @::*pkg-state*))
                                  (@::load-pkg-body pkg-name seen))))))
      (if (vl-catch-all-error-p catch-result%)
        (@::@log "ERROR" (vl-catch-all-error-message catch-result%)))
      (princ))))
(defun @::load-pkg-body (pkg-name seen / required% compatible-p dep-names%)
  ""
  (@::@log "INFO" (strcat (_ "Loading") " " pkg-name " ... "))
  (if (findfile (strcat "packages/" pkg-name "/pkg.lsp"))
    (@::@load (strcat pkg-name "/pkg")))
  (if (findfile (strcat @::*prefix* "locale/" pkg-name "." @::*lang* ".lang"))
    (@::load-locale pkg-name))
  (setq compatible-p (and
                       (member pkg-name (mapcar 'car @::*local-pkgs*))
                       (or
                         (null (@::pkg (@::get-local-pkg-info pkg-name) ':compatible))
                         (and
                           (@::pkg (@::get-local-pkg-info pkg-name) ':compatible)
                           (eq
                             @::cad-platform
                             (@::pkg (@::get-local-pkg-info pkg-name) ':compatible))))))
  (if compatible-p
    (progn
      (setq @::*stack-curr-package* (cons pkg-name @::*stack-curr-package*))
      (setq required% (cdr (assoc ':required (cdr (assoc pkg-name @::*local-pkgs*)))))
      (setq dep-names% (cond
                         ((eq 'STR (type-of required%))
                          (list (car (@::parse-version-constraint required%))))
                         ((eq 'LIST (type-of required%))
                          (mapcar
                            (function (lambda (x) (car (@::parse-version-constraint x))))
                            required%))
                         (t nil)))
      (cond
        ((eq 'STR (type-of required%))
         (@::resolve-single-dep required% seen))
        ((eq 'LIST (type-of required%))
         (@::resolve-list-deps required% seen)))
      (foreach dep-name dep-names%
        (if (null (member dep-name @::*pkg-state*))
          (progn
            (@::load-pkg dep-name seen)
            (if (null (member dep-name @::*pkg-state*))
              (@::@log "WARN" (strcat (_ "Dependency not loaded: ") dep-name))))))
      (@::load-pkg-files pkg-name)
      (@::mark-pkg-loaded pkg-name))
    (@::handle-incompatible-pkg pkg-name)))
(defun @::load-vlx (vlx-name command-name)
  ""
  (if
    (and
      is-zwcad
      (= ".vlx" (substr vlx-name (- (strlen vlx-name) 3))))
    (setq vlx-name (strcat (substr vlx-name 1 (- (strlen vlx-name) 3)) ".vls")))
  (if (null (findfile (strcat "packages/" vlx-name)))
    (@::down-pkg-file (@::uri) vlx-name edition))
  (if (null (type command-name))
    (if (findfile (strcat "packages/" vlx-name))
      (load (strcat "packages/" vlx-name))))

  (if
    (or
      (eq 'subr (type command-name))
      (eq 'sym (type command-name)))
    (command-name)
    (princ (_ "File incomplete"))))


;; ── sub-system/package/version.lsp ──────────────────────────────────────────
;; @depends base-function
;; @provides package-version
(vl-load-com)
(defun @::upgrade ()
  ""
  (and
    (@::load-module 'pkgman)
    (@::install-mini-sys)
    (@::updatelib)
    (if (@::package-upgrade-all)
      (progn
        (@::@log "INFO" "upgrade some packages,need re-init @lisp")
        (@::load-local-pkg)
        (if @::*menu* (@::make-menu)))
      (@::@log "INFO" "no package need upgrade"))))
;;  安装/更新 核心程序
(defun @::prefetch-pkg-cache (/ pkgs-to-prefetch)
  "后台预取常用包元数据到缓存，加速后续加载"
  (setq pkgs-to-prefetch (vl-remove-if
                           (function (lambda (p) (member p @::*pkg-state*)))
                           '("base" "string" "block" "layer" "entity" "ui" "math")))
  (foreach pkg pkgs-to-prefetch
    (if (null (findfile (strcat "packages/" pkg "/pkg.lsp")))
      (vl-catch-all-apply
        (function (lambda ()
           (if (boundp '@::down-file)
             (@::down-file (strcat pkg "/pkg.lsp")))))
        nil))))
;; ---- Package version constraints ----
(defun @::parse-version-constraint (str / op-parts)
  "解析版本约束字符串如 \"base>=1.2\" → \"base\" \">=\" \"1.2\""
  (setq op-parts (cond
                    ((vl-string-search ">=" str)
                     (list
                       (substr str 1 (vl-string-search ">=" str))
                       ">="
                       (substr str (+ (vl-string-search ">=" str) 3))))
                    ((vl-string-search "<=" str)
                     (list
                       (substr str 1 (vl-string-search "<=" str))
                       "<="
                       (substr str (+ (vl-string-search "<=" str) 3))))
                    ((vl-string-search ">" str)
                     (list
                       (substr str 1 (vl-string-search ">" str))
                       ">"
                       (substr str (+ (vl-string-search ">" str) 2))))
                    ((vl-string-search "<" str)
                     (list
                       (substr str 1 (vl-string-search "<" str))
                       "<"
                       (substr str (+ (vl-string-search "<" str) 2))))
                    ((vl-string-search "=" str)
                     (list
                       (substr str 1 (vl-string-search "=" str))
                       "="
                       (substr str (+ (vl-string-search "=" str) 2))))
                   (t (list str nil nil))))
  op-parts)
(defun @::version-satisfies-p (version constraint)
  "检查 version 是否满足 constraint。constraint 如 \">=\" \"1.2\""
  (if (null constraint)
    t
    (cond
      ((= (car constraint) ">=") (not (@::compare-version (cadr constraint) version)))
      ((= (car constraint) "<=") (not (@::compare-version version (cadr constraint))))
      ((= (car constraint) ">") (@::compare-version version (cadr constraint)))
      ((= (car constraint) "<") (@::compare-version (cadr constraint) version))
      ((= (car constraint) "=") (not (@::compare-version version (cadr constraint))))
      (t t))))
(defun @::get-reverse-deps (pkg-name / pkg%)
  "获取依赖指定包的所有已安装包列表"
  (vl-remove
    nil
    (mapcar
      (function (lambda (pkg%)
         (if (member pkg-name (@::get-pkg-deps (cdr (assoc pkg% @::*local-pkgs*))))
           pkg%
           nil)))
      @::*pkg-in-use*)))
(defun @::pkg-deps-tree (pkg-name / depth seen info deps)
  "递归显示包依赖树"
  (defun @::pkg-deps-tree-rec (name depth)
    (if (not (member name seen))
      (progn
        (setq seen (cons name seen))
        (princ (strcat "\n" (@::make-string (* 2 depth) 32) name))
        (if (setq info (cdr (assoc name @::*local-pkgs*)))
          (progn
            (setq deps (@::get-pkg-deps info))
            (foreach d deps
              (@::pkg-deps-tree-rec d (1+ depth))))))))
  (setq seen '())
  (princ (strcat "\n@lisp: " (_ "Dependency tree for: ") pkg-name))
  (@::pkg-deps-tree-rec pkg-name 0)
  (princ))
(defun @::pkg-reverse-deps-tree (pkg-name / depth seen)
  "递归显示反向依赖树（哪些包依赖此包）"
  (defun @::pkg-rev-tree-rec (name depth)
    ""
    (if (not (member name seen))
      (progn
        (setq seen (cons name seen))
        (princ (strcat "\n" (@::make-string (* 2 depth) 32) name))
        (foreach rdep (@::get-reverse-deps name)
          (@::pkg-rev-tree-rec rdep (1+ depth))))))
  (setq seen '())
  (princ (strcat "\n@lisp: " (_ "Reverse dependency tree for: ") pkg-name))
  (@::pkg-rev-tree-rec pkg-name 0)
  (princ))
(defun @::pkg-check-upgrades (/ pkgs pkg local-ver server-ver info np)
  "检查所有已安装包是否有更新版本"
  (setq pkgs @::*pkg-in-use*)
  (if (null pkgs)
    (princ (strcat "\n@lisp: " (_ "No packages installed.")))
    (progn
      (princ (strcat "\n@lisp: " (_ "Checking package updates...")))
      (if (boundp '@::package-update) (@::package-update))
      (foreach pkg pkgs
        (setq info (cdr (assoc pkg @::*local-pkgs*)))
        (if info
          (progn
            (setq local-ver (@::pkg info :version))
            (setq server-ver (if
                               (and
                                 (boundp '@::*pkgs*)
                                 (setq np (assoc pkg @::*pkgs*)))
                               (@::pkg np :version)
                               nil))
            (if (and server-ver (@::compare-version server-ver local-ver))
              (princ
                (strcat
                  "\n  "
                  pkg
                  ": "
                  local-ver
                  " -> "
                  server-ver
                  " ("
                  (_ "update available")
                  ")"))
              (princ (strcat "\n  " pkg ": " local-ver " (" (_ "latest") ")"))))))
      (princ))))
(defun C:@UPGRADE (/ pkgs pkg local-ver server-ver choice info np)
  "升级所有有可用更新的已安装包"
  (if (not (boundp '@::*pkgs*))
    (progn
      (princ (strcat "\n@lisp: " (_ "Updating package list...")))
      (@::package-update)))
  (setq pkgs '())
  (foreach pkg @::*pkg-in-use*
    (setq info (cdr (assoc pkg @::*local-pkgs*)))
    (if
      (and
        info
        (setq local-ver (@::pkg info :version))
        (setq np (assoc pkg @::*pkgs*))
        (setq server-ver (@::pkg np :version))
        (@::compare-version server-ver local-ver))
      (setq pkgs (cons (list pkg local-ver server-ver) pkgs))))
  (if (null pkgs)
    (princ (strcat "\n@lisp: " (_ "All packages are up to date.")))
    (progn
      (princ (strcat "\n@lisp: " (_ "Packages with updates available:")))
      (foreach p pkgs
        (princ (strcat "\n  " (car p) ": " (cadr p) " -> " (caddr p))))
      (princ (strcat "\n" (_ "Upgrade all? (Y/n): ")))
      (setq choice (strcase (read-line)))
      (if (or (= choice "") (= choice "Y") (= choice "YES"))
        (progn
          (foreach p pkgs
            (princ (strcat "\n  " (_ "Upgrading ") (car p) "... "))
            (if (@::package-upgrade (car p))
              (princ (_ "OK"))
              (princ (_ "failed"))))
          (princ (strcat "\n@lisp: " (_ "Upgrade complete.")))))))
  (princ))


;; ── sub-system/package/cmd.lsp ──────────────────────────────────────────
;; @depends base-function package-load package-version package-persist package-lock
;; @provides package-cmd
(vl-load-com)
(defun C:@U () (@::upgrade))
(defun C:@P () (and (@::load-module 'pkgman) (@::package-manager-dialog)))
; 包管理
(defun C:@I () (and (@::load-module 'pkgman) (@::package-install-ui)))
(defun C:@L ()
  (@::package-list-local))
(defun C:@DEP (/ pkg-name choice)
  "显示包依赖树。输入包名显示正向依赖，加 -r 显示反向依赖。"
  (setq pkg-name (getstring T (strcat "\n" (_ "Package name") " ("
                                       (_ "Enter for all") ", -r " (_ "for reverse") "): ")))
  (if (= "" pkg-name)
    (progn
      (princ (strcat "\n" (_ "Installed packages:")))
      (foreach p @::*pkg-in-use*
        (princ (strcat "\n  " p)))
      (princ))
    (if (wcmatch pkg-name "-r*")
      (progn
        (setq pkg-name (substr pkg-name 4))
        (if (= "" pkg-name)
          (setq pkg-name (getstring T (strcat "\n" (_ "Package name") ": "))))
        (if (/= "" pkg-name)
          (@::pkg-reverse-deps-tree pkg-name)
          (princ (strcat "\n" (_ "No package specified.")))))
      (@::pkg-deps-tree pkg-name)))
  (princ))
(defun @::package-remove (pkg-name / pkg-info% reverse-deps uri)
  "删除软件包. return T or nil."
  (if
    (and
      (eq 'str (type-of pkg-name))
      (null (vl-string-search "/" pkg-name))
      (null (vl-string-search "\\" pkg-name))
      (member pkg-name (mapcar (function car) @::*local-pkgs*)))
    (progn
      (setq reverse-deps (@::get-reverse-deps pkg-name))
      (if reverse-deps
        (progn
          (@::@log
            "ERROR"
            (strcat
              "Can not remove "
              pkg-name
              ": required by "
              (vl-princ-to-string reverse-deps)))
          nil)
        (progn
          (setq pkg-info% (cdr (assoc pkg-name @::*local-pkgs*)))
          (@::pkg-fire-hooks pkg-name 'on-unload)
          (setq uri (cdr (assoc :url pkg-info%)))
          (foreach pkg-file% (mapcar (function @::pkg-fas-file) (cdr (assoc :files pkg-info%)))
            (vl-file-delete (strcat @::*prefix* pkg-name "/" pkg-file%)))
          (setq @::*pkg-in-use* (vl-remove pkg-name @::*pkg-in-use*))
          (@::save-pkg-in-use)
          (@::remove-pkg-menu pkg-name)
          (setq @::*flag-menu-need-update* T)
          (vl-catch-all-apply (function (lambda () (@::event-emit 'package-removed (list pkg-name)))) nil)
          (vl-catch-all-apply (function (lambda () (@::audit-log :package.remove
            (list (cons :target pkg-name) (cons :result :success))))) nil)
          (if
            (and
              (boundp '@::config-sync-packages-push)
              (@::valid-user)
              (/= "" (@::get-config '@::user-token)))
            (@::config-sync-packages-push))
          T)))
    (progn
      (@::@log "ERROR" (strcat "Can not find installed package: " pkg-name))
      nil)))
(defun C:@R (/ pkg-name)
  (setq pkg-name (getstring (_ "Please input the package name that you will remove: ")))
  (if (/= "" (strlen pkg-name))
    (@::package-remove (strcase pkg-name T)))
  (if @::*flag-menu-need-update*
    (C:@m)))


;; ── sub-system/user-manager.lsp ──────────────────────────────────────────
;; @depends base-function net config-manager
;; @provides user-manager
(defun @::scale (scale)
  (if (or (eq 'int (type scale)) (eq 'real (type scale)))
    (* (@::get-config '@::draw-scale) scale)
    (@::get-config '@::draw-scale)))
(defun @::check-userinfo (/ info)
  (if
    (or
      (= "" (@::get-config '@::user-email))
      (= "" (@::get-config '@::user))
      (= "anonymous" (@::get-config '@::user))
      (= "" (@::get-config '@::user-phone)))
    nil
    T))
(setq @::valid-user @::check-userinfo)

(defun anti-crack ()
  (if
    (and
      (boundp 'my-fingerprint)
      (/= (apply '+ my-fingerprint) @::*fingerprint-checksum*))
    (repeat 10
      (prompt (_ "The version you are using has been tampered with. Please use it carefully."))
      (prompt "\n"))))
(setq @::*userinfo* (list
    (cons "acadver" (getvar "acadver"))
    (cons "cadproduct" (cond (is-zwcad "ZWCAD") (is-gcad "GStarCAD") (t "AutoCAD")))))
(defun @::sslp ()
  (@::init-uris)
  (@::internetp))
(defun @::session-valid-p (/ token email)
  "检查当前会话是否有效。返回 T 表示有效，nil 表示需要重新登录。"
  (setq token (@::get-config '@::user-token))
  (setq email (@::get-config '@::user-email))
  (and token
    email
    (/= "" token)
    (/= "" email)
    (/= "anonymous" (@::get-config '@::user))
    (@::get-config '@::user-login-time)
    (< (- (atof (@::timestamp)) (atof (@::get-config '@::user-login-time))) @::*seconds-per-day*)))

(defun @::session-clear ()
  "清除当前会话，强制重新登录。"
  (@::set-config '@::user-token "")
  (@::set-config '@::user "")
  (@::set-config '@::user-email "")
  (@::set-config '@::user-phone "")
  (@::set-config '@::user-login-time "")
  (@::set-config '@::user-login-type "")
  (princ (strcat "\n" (_ "会话已清除。请使用 C:@LOGIN 重新登录。") "\n")))

(defun @::show-login-progress (state max-wait / n dots)
  "显示登录进度动画。返回 T=成功 nil=超时"
  (setq n 0)
  (setq dots "")
  (princ (strcat "\n" (_ "等待扫码登录")))
  (while (and (< n max-wait) (= (@::get-filesize-from-ssl state) 0))
    (setq n (1+ n))
    (setq dots (strcat dots "."))
    (princ ".")
    (if (= 0 (rem n 10))
      (progn
        (princ (strcat " " (itoa (- max-wait n)) "s")))
      (if (= 0 (rem n 20))
        (princ "\n")))
    (if (= 0 (rem n 5))
      (setvar "modemacro" (strcat (_ "正在等待扫码登录... ") (itoa n) "/" (itoa max-wait))))
    (sleep 1))
  (setvar "modemacro" "")
  (if (> n 10)
    (confirm (list (_ "登录是否遇到问题？") (_ "成功请按确定") (_ "失败请按取消。"))))
  (> (@::get-filesize-from-ssl state) 10))

(defun @::save-login-session (wxid /)
  "保存登录会话到配置和文件。"
  (@::write-wxid wxid)
  (@::set-config '@::user-login-time (@::timestamp))
  (@::set-config '@::user-login-type "wechat")
  (setq @::*userinfo* (list
      (cons "wxid" wxid)
      (cons "acadver" (getvar "acadver"))
      (cons "cadproduct" (cond (is-zwcad "ZWCAD") (is-gcad "GStarCAD") (t "AutoCAD")))))
  (princ (strcat "\n✅ " (_ "微信登录成功！") "\n")))

(defun @::write-wxid (wxid / fp)
  (setq fp (vl-catch-all-apply 'open (list (strcat @::*prefix-config* "wx-id") "w")))
  (if (not (vl-catch-all-error-p fp))
    (progn
      (write-line wxid fp)
      (close fp)
      t)
    (progn
      (@::@log "ERROR" (strcat (_ "无法写入 ") @::*prefix-config* "wx-id"))
      nil)))

(defun @::poll-wxid (state / n wxid)
  (setq n 0)
  (while (and (< n 40) (= (@::get-filesize-from-ssl state) 0))
    (setq n (1+ n))
    (sleep 1))
  (if (> n 10)
    (confirm (list (_ "登录是否遇到问题？") (_ "成功请按确定") (_ "失败请按取消。"))))

  (if (and (> (@::get-filesize-from-ssl state) 10)
      (setq wxid (@::http-request (strcat @::*uri-ssl* "/stable/" state))))
    (progn
      (@::save-login-session wxid)
      wxid)
    (progn
      (@::@log "WARN" (_ "登录超时或服务器未返回 wxid"))
      nil)))

(defun @::@login (/ state url)
  (if (@::uri)
    (progn
      (@::load-module 'pkgman)
      (@::init-uris)
      (if (@::session-valid-p)
        (progn
          (princ (strcat "\n" (_ "当前会话有效，无需重新登录。") "\n"))
          (princ (strcat "  " (_ "用户: ") (@::get-config '@::user-email) "\n"))
          (princ (strcat (_ "如需重新登录，请先使用 session-clear 清除会话。") "\n"))
          (princ (strcat (_ "或直接使用 C:@LOGIN 命令强制重新登录。") "\n"))
          nil)
        (progn
          (setq state (strcat (rtos (@::acadver) 2 1) "-" (@::timestamp)
              (if @::*machineid* @::*machineid* "")))
          (setq url (strcat @::*uri-ssl* "/user/wechat/weblogin?state=" state
              "&wxid=" (if (@::get-wxid) (car (@::get-wxid)) "")
              "&acadver=" (rtos (@::acadver) 2 1)))
          (if (or (not is-autocad) (< (@::acadver) 20.1) (= "http://localhost:8100" (@::uri)))
            (progn
              (@::open-url url)
              (@::show-login-progress state 40)
              (@::poll-wxid state))
            (progn
              (showhtmlmodalwindow url)
              (@::poll-wxid state))))))
    (progn
      (princ (strcat "\n❌ " (_ "无法连接 @lisp 服务器，请检查网络配置。") "\n"))
      nil)))
(defun @::get-wxid ()
  (@::with-file-lines
    (strcat @::*prefix-config* "wx-id")
    '(lambda (line)
      (setq unionid line)))
  (if unionid
    (@::string-to-list unionid " ")))

;; ═══════════════════════════════════════════════════════
;; Enterprise SSO login
;; ═══════════════════════════════════════════════════════
(defun @::enterprise-login (/ sso-type sso-url token-callback)
  "企业 SSO 登录入口。支持 LDAP/SAML/OIDC。
  向 @lisp 服务端发起认证请求，服务端代理到企业 IdP。
  成功后返回 token，存入 @::user-token。

  服务端 API 依赖:
  GET  /auth/sso/login?type=ldap&url=<sso-url>&client_id=<id>
  POST /auth/sso/callback  <- 接收 IdP 回调
  GET  /auth/sso/token?state=<state>  <- 客户端轮询获取 token"
  (setq sso-type (@::get-config '@::sso-type))
  (setq sso-url (@::get-config '@::sso-url))
  (if (and (> sso-type 0) (/= "" sso-url))
    (if (@::internetp)
      (progn
        (@::load-module 'network)
        ((lambda (auth-url)
            (@::open-url auth-url)
            (princ (strcat "\n" (_ "正在等待企业认证完成...") "\n"))
            (princ (strcat (_ "如果浏览器未自动打开，请访问: ") auth-url "\n"))
            (prompt (strcat (_ "认证完成后请在 CAD 中输入 y 或按 Enter 继续...") " "))
            (getstring)
            ;; 从服务器获取 token（服务端在 SSO 回调后暂存 token）
            (setq token-callback (@::http-request
                (strcat (@::uri) "/auth/sso/token?machineid=" @::*machineid*)))
            (if token-callback
              ((lambda (result)
                  (if (cdr (assoc "token" result))
                    (progn
                      (@::set-config '@::user-token (cdr (assoc "token" result)))
                      (@::set-config '@::user (cdr (assoc "user" result)))
                      (@::set-config '@::user-email (cdr (assoc "email" result)))
                      (if (boundp '@::fetch-user-role) (@::fetch-user-role))
                      (@::@log
                        "INFO"
                        (strcat
                          "SSO login successful. User: "
                          (cdr (assoc "user" result))))
                      (cdr (assoc "token" result)))
                    (progn
                      (@::@log "ERROR" "SSO login failed: no token returned")
                      nil)))
                (json:parse token-callback))
              nil))
          (strcat
            (@::uri)
            "/auth/sso/login"
            "?type="
            (cond
              ((= sso-type 1) "ldap")
              ((= sso-type 2) "saml")
              ((= sso-type 3) "oidc")
              (t "ldap"))
            "&url="
            (@::urlencode sso-url)
            "&client_id="
            (@::urlencode (@::get-config '@::sso-client-id))
            "&machineid="
            @::*machineid*
            "&locale="
            @::*locale*))
        (progn
          (@::@log "ERROR" "SSO login failed: network unavailable")
          nil))
      (progn
        (princ "\nSSO not configured. Use C:@LOGIN for standard login.\n")
        nil))))


;; ── sub-system/update.lsp ──────────────────────────────────────────
;; @depends base-function net config-manager
;; @provides update
(defun @::check-new-version (days / fp julian *error*)
  "检查并更新核心系统版本,更新返回t,没更新返回nil"
  (setq *error* (lambda (msg)
      (cond
        ((= msg "quit / exit abort")
          (princ "Exit from @lisp bootstrap"))
        ;; add other msg
        (t
          (if (boundp '@::*error*) (@::*error* msg))
          (princ msg))
  )))
  (if (and (null (@::offline-mode-p))
      (= 1 (vl-bb-ref '@::netstate))
      (<= 1 (@::get-config '@::autoupdate))
      (@::internetp)
      (findfile (strcat @::*prefix* ".check-newversion")))
    (progn
      (@::with-file-lines (strcat @::*prefix* ".check-newversion")
        '(lambda (line)
          (setq julian (atoi line))))
      (if (> (- (fix (getvar "DATE")) julian) days)
        (progn
          (if (null (member 'pkgman @::*modules*))
            (@::load-module 'pkgman))
          (@::@log-server "upgrade @lisp.")
          (cond
            ((setq str-Response (@::http-request (strcat (@::uri) "/stable/version.lsp")))
              (@::safe-eval (read str-Response)))
            (t
              (@::down-file "version.lsp")
              (sleep 1)
              (load "version")))
          (if (@::compare-version new-version @::version)
            (progn
              (@::upgrade-mini-sys)
              (@::@log "INFO" (strcat (_"Upgrade") " @lisp. " (_"version to ")
                  new-version "\n "
                  (_"Auto upgrade function only upgrade kernel. If you want upgrade all system. Please input @U.")))
              (@::show-whats-new new-version @::version)
              (sleep 2)
          ))
          (setq fp  (vl-catch-all-apply 'open (list (strcat @::*prefix* ".check-newversion") "w")))
          (if (not (vl-catch-all-error-p fp))
            (progn
              (write-line (rtos (getvar "DATE")) fp)
              (close fp)))
          (if (or(and (@::load-module 'pkgman)
                (@::check-new-packages))
              (@::compare-version new-version @::version))
            (progn(load "@lisp")(@::init-once)))
          t
    )))
    (progn
      (setq fp  (vl-catch-all-apply 'open (list (strcat @::*prefix* ".check-newversion") "w")))
      (if (not (vl-catch-all-error-p fp))
        (progn
          (write-line (rtos (getvar "DATE")) fp)
          (close fp)))
      nil
  ))
)
(defun @::growth-plan ()
  (@::load-module 'pkgman)(growth-plan))


;; ── sub-system/condition/cn-commands.lsp ──────────────────────────────────────────
;; @depends base-function i18n
;; @provides condition-cn-commands
;; 第三方包可注册的回调钩子
(setq @::*unknown-command-hooks* nil
      @::*dbclick-hooks*         nil)
;; ═══════════════════════════════════════════════════════
;; 中文→命令映射表 — 输入中文自动匹配
(setq @::*cn-commands* '(("安装" . "C:@I")
                          ("装包" . "C:@I")
                          ("卸载" . "C:@R")
                          ("删包" . "C:@R")
                          ("帮助" . "C:@H")
                          ("设置" . "C:@S")
                          ("配置" . "C:@S")
                          ("升级" . "C:@U")
                          ("更新" . "C:@U")
                          ("菜单" . "C:@M")
                          ("面板" . "C:@@")
                          ("命令" . "C:@@")
                          ("聊天" . "C:@C")
                          ("列表" . "C:@L")
                          ("关于" . "C:@V")
                          ("修复" . "C:@F")
                          ("清缓存" . "C:@K")
                          ("缓存" . "C:@K")
                          ("批量" . "C:@BATCH")
                          ("代理" . "C:@AI")
                          ("退出" . "exit")
                          ("关于" . "C:@V")
                          ("chat" . "C:@C")))
;; 哈希表镜像，用于 O(1) 查找
(setq @::*cn-commands-hash* nil)
(defun @::cn-commands-build-hash (/ ht)
  "从 @::*cn-commands* 构建哈希表"
  (if (null @::*cn-commands-hash*)
    (progn
      (setq ht (vlax-create-object "Scripting.Dictionary"))
      (foreach pair @::*cn-commands*
        (vlax-invoke ht 'Add (car pair) (cdr pair)))
      (setq @::*cn-commands-hash* ht))))
(defun @::cn-command-lookup (cn-name)
  "O(1) 查找中文命令。如果哈希表不可用，回退到 assoc 线性查找。"
  (if @::*cn-commands-hash*
    (vl-catch-all-apply (function (lambda () (vlax-get-property @::*cn-commands-hash* 'Item cn-name))) nil)
    (cdr (assoc cn-name @::*cn-commands*))))



(defun @::register-cn-command (cn-name cmd)
  "注册中文命令映射。cn-name: 中文命令名, cmd: 要执行的 CAD 命令字符串。
  例如: (@::register-cn-command \"画墙\" \"C:WALL\")"
  (if (not (assoc cn-name @::*cn-commands*))
    (progn
      (setq @::*cn-commands* (append @::*cn-commands* (list (cons cn-name cmd))))
      (if @::*cn-commands-hash*
        (vl-catch-all-apply (function (lambda ()
           (vlax-invoke @::*cn-commands-hash* 'Add cn-name cmd))) nil)))
    (princ (strcat "\n" cn-name " " (_ "already exists.") "\n"))))
(defun @::on-unknown-command (handler)
  "注册未知命令处理回调。handler 接收命令字符串参数，返回表达式字符串或 nil"
  (setq @::*unknown-command-hooks* (append @::*unknown-command-hooks* (list handler))))
(defun @::on-double-click (handler)
  "注册双击处理回调。handler 接收 (point) 参数"
  (setq @::*dbclick-hooks* (append @::*dbclick-hooks* (list handler))))
(defun @::enable-command-reactor ()
  (if (null @::*react-cmds*)
    (setq @::*react-cmds* (vlr-command-reactor nil '((:vlr-unknownCommand . parse-cmdunknown))))
    (vlr-add @::*react-cmds*)))
(defun @::disable-command-reactor ()
  (if @::*react-cmds*
    (vlr-remove @::*react-cmds*)))


;; ── sub-system/condition/nlp.lsp ──────────────────────────────────────────
;; @depends base-function net condition-cn-commands cache
;; @provides condition-nlp
(defun @::ensure-str (expr)
  "确保 expr 为字符串类型，若是符号则转换为字符串"
  (if (null (eq 'str (type expr)))
    (vl-prin1-to-string expr)
    expr))
(defun @::odds-cmd (str str-cmd / lst-cmd lst-str lst-match)
  "计算两个字符串的相似度比例（0~1），用于命令模糊匹配"
  "float"
  "(@::odds-cmd \"画圆\" \"画一个圆\")"
  (setq lst-str (string:s2l-ansi str))
  (if (null lst-str)
    (setq lst-str nil))
  (setq lst-match
    (if lst-str
      (vl-remove
        nil
        (mapcar
          (function (lambda (x)
             (member x (string:s2l-ansi str-cmd))))
          lst-str))
      nil))
  (if (and (= 0 (length lst-str)) (= 0 (length (string:s2l-ansi str-cmd))))
    1.0
    (/ (length lst-match) (float (length lst-str)))))
(defun @::get-cmd-by-str (str)
  "从本地菜单中模糊匹配命令，返回按相似度排序的匹配列表"
  "list of (cmd . odds) or nil"
  "(@::get-cmd-by-str \"画圆\")"
  (setq str (strcase str))
  (if (/= "" str)
    (vl-sort
      (vl-remove
        nil
        (mapcar
          (function (lambda (x / ratio)
             (if (> (setq ratio (@::odds-cmd str (strcase (car x)))) 0.75)
               (cons x ratio)
               nil)))
          (append
            (mapcan 'cdr @::*menu*)
            (mapcan 'cdr (evaltrans @::*menu-man*))
            @::*hidden-voices*)))
        (function (lambda (x y)
           (> (cdr x) (cdr y)))))))
(defun @::get-cmd-from-web (str)
  "从远程菜单匹配命令，返回按相似度排序的匹配列表"
  "list of (cmd . odds) or nil"
  "(@::get-cmd-from-web \"画墙\")"
  (if (or @::@get @::*remote-menu* (@::load-module 'pkgman))
    (progn
      (setq str (strcase str))
      (if (/= "" str)
        (vl-sort
          (vl-remove
            nil
            (mapcar
              (function (lambda (x / ratio)
                 (if (> (setq ratio (@::odds-cmd str (strcase (car x)))) 0.75)
                   (cons x ratio)
                   nil)))
              (append (mapcan 'cdr @::*remote-menu*))))
          (function (lambda (x y)
             (> (cdr x) (cdr y)))))))))
(if (not (boundp 'flagslow)) (setq flagslow nil))
;; ═══════════════════════════════════════════════════════
;; 云 NLP 匹配 — 将输入发送到 /api/nlp/match
;; ═══════════════════════════════════════════════════════
(defun @::nlp-cache-init ()
  "惰性初始化 NLP 缓存"
  (or @::*nlp-cache*
      (setq @::*nlp-cache*
        (if (setq @::*nlp-cache* (@::cache-load "nlp" "cache" @::*date-30-minutes*))
          (read @::*nlp-cache*)
          nil))))
(defun @::query-nlp-cloud (text / result)
  "向 /api/nlp/match 发送中文文本，返回 (type . value)
   type: 'command → (command . \"CIRCLE\")
         'install  → (install pkg-name . \"C:CMD\")
         'chat     → (chat . \"response text\")
         nil       → 网络失败或无匹配"
  (@::nlp-cache-init)
  ;; 查缓存
  (if (setq result (cdr (assoc text @::*nlp-cache*)))
    result
    (progn
      (@::load-module 'network)
      (@::load-module 'pkgman)
      (vl-catch-all-apply
        (function (lambda (/ response json)
           (setq response (@::postjson
                            (strcat (@::uri) "/api/nlp/match")
                            (strcat "{\"text\":"
                                    (vl-prin1-to-string text)
                                    ",\"locale\":\""
                                    @::*locale*
                                    "\"}")))
           (if response
             (progn
               (setq json (json:parse response))
               (cond
                 ((and (cdr (assoc :type json)) (= "command" (cdr (assoc :type json))))
                  (setq result (cons 'command (cdr (assoc :cmd json)))))
                 ((and (cdr (assoc :type json)) (= "install" (cdr (assoc :type json))))
                  (setq result (list 'install (cdr (assoc :pkg json)) (cdr (assoc :cmd json)))))
                 ((and (cdr (assoc :type json)) (= "chat" (cdr (assoc :type json))))
                  (setq result (cons 'chat (cdr (assoc :text json))))))
               ;; 缓存结果 30 分钟，持久化到磁盘
               (setq @::*nlp-cache* (cons (cons text result) @::*nlp-cache*))
               (if (> (length @::*nlp-cache*) 50)
                 (setq @::*nlp-cache* (reverse (cdr (reverse @::*nlp-cache*)))))
               (@::cache-store "nlp" "cache"
                 (vl-prin1-to-string @::*nlp-cache*) @::*date-30-minutes*))
             (setq result nil))))
        nil)
      result)))
(defun @::post-command (cmd)
  "向 CAD 发送命令字符串，自动处理类型转换和换行符"
  "nil"
  "(@::post-command \"C:CIRCLE\")"
  (if cmd
    (vla-postcommand *DOC* (strcat (@::ensure-str cmd) (chr 10)))))
(defun @::cmd-menu-items ()
  "获取所有可用的菜单项命令列表"
  "list of (name . cmd)"
  "(@::cmd-menu-items)"
  (append
    (mapcan 'cdr @::*menu*)
    (mapcan 'cdr (evaltrans @::*menu-man*))
    @::*hidden-voices*))
(defun @::cmd-match-direct (input)
  "直接匹配中文→命令映射表（使用哈希表 O(1) 查找），匹配成功则执行并返回 T"
  "T or nil"
  "(@::cmd-match-direct \"安装\")"
  (let ((expr (@::cn-command-lookup input)))
    (if expr
      (progn
        (@::post-command expr)
        t))))
(defun @::cmd-match-menu (input)
  "精确匹配已安装菜单项，匹配成功则执行并返回 T"
  "T or nil"
  "(@::cmd-match-menu \"画圆\")"
  (let ((items (@::cmd-menu-items)))
    (if (member input (mapcar 'car items))
      (let ((expr (cadr (assoc input items))))
        (if expr
          (progn
            (@::post-command expr)
            t))))))
(defun @::cmd-match-fuzzy (input)
  "模糊匹配本地命令，通过字符串相似度匹配菜单项"
  "T or nil"
  "(@::cmd-match-fuzzy \"画圆\")"
  (let ((lst-cmd (@::get-cmd-by-str input)) expr)
    (if lst-cmd
      (progn
        (setq expr (if (= 1 (length lst-cmd))
                     (cadaar lst-cmd)
                     (ui:button-select
                       (_ "Please select command to run.")
                       (mapcar 'caar lst-cmd))))
        (if expr
          (progn
            (@::post-command expr)
            t))))))
(defun @::cmd-match-web (input)
  "从远程菜单匹配命令，自动安装所需包"
  "T or nil"
  "(@::cmd-match-web \"画墙\")"
  (let ((lst-cmd (@::get-cmd-from-web input)) expr pkg-to-ins)
    (if lst-cmd
      (progn
        (if (null @::package-install-mutt)
          (@::load-module 'pkgman))
        (if (= 1 (length lst-cmd))
          (progn
            (@::package-install-mutt (cadr (cdaar lst-cmd)))
            (@::load-pkg (cadr (cdaar lst-cmd)) '())
            (setq expr (cadaar lst-cmd)))
          (progn
            (setq expr       (ui:button-select
                               (_ "Please select command to run.")
                               (mapcar 'caar lst-cmd))
                  pkg-to-ins (last (assoc expr (mapcar 'car lst-cmd))))
            (@::package-install-mutt pkg-to-ins)
            (@::load-pkg pkg-to-ins '())
            (setq expr (nth 1 (assoc expr (mapcar 'car lst-cmd))))))
        (if expr
          (progn
            (@::post-command expr)
            t))))))
(defun @::cmd-match-cloud-nlp (input)
  "通过云 NLP 匹配命令，支持 command/install/chat 三种类型"
  "T or nil"
  "(@::cmd-match-cloud-nlp \"画一个圆\")"
  (let ((nlp-result (@::query-nlp-cloud input)) expr pkg-to-ins)
    (if nlp-result
      (progn
        (cond
          ((eq 'command (car nlp-result))
           (setq expr (cdr nlp-result))
           (princ (strcat "\n@lisp: " (_ "Matched via cloud NLP") " → " expr)))
          ((eq 'install (car nlp-result))
           (setq pkg-to-ins (cadr nlp-result)
                 expr      (caddr nlp-result))
           (princ (strcat "\n@lisp: " (_ "Cloud suggests package") " " pkg-to-ins))
           (if (@::package-install-mutt pkg-to-ins)
             (@::load-pkg pkg-to-ins '())))
          ((eq 'chat (car nlp-result))
           (princ (strcat "\n@lisp: " (cdr nlp-result)))))
        (if expr
          (progn
            (@::post-command expr)
            t))))))
(defun @::cmd-ai-chat-fallback (input)
  "AI 聊天兜底：输入较长且无匹配时尝试 AI 聊天"
  (if (and (null flagslow) (>= (strbytelen input) 4))
    (progn
      (@::load-module 'pkgman)
      (@::load-module 'aibot)
      (if @::chat (@::chat input))
      (princ "\n\n>>>>>>>>>>>>>>>>>>")
      (princ))))

(defun @::cmd-ai-fallback (input)
  "AI fallback 处理未知命令，尝试 AI 代码生成、聊天和用户注册的回调"
  "T or nil"
  "(@::cmd-ai-fallback \"画一个圆\")"
  (let ((expr nil))
    (if (@::load-module 'nlp)
      (progn
        (@::speak input)
        (setq expr (@nlp::gen-code (@nlp::parse-corpus (string:to-lst input ";"))))
        (@::@debug "INFO" (vl-prin1-to-string expr))
        (if expr
          (@::post-command expr))))
    (if (null expr)
      (@::cmd-ai-chat-fallback input))
    (foreach hook @::*unknown-command-hooks*
      (if (null expr)
        (setq expr (hook input))))
    (if expr
      (progn
        (@::post-command expr)
        t)
      nil)))
(defun parse-cmdunknown (param1 param2 / input)
  "解析未知命令 -> 依次尝试 6 种匹配策略"
  "T or nil"
  "(parse-cmdunknown nil '(\"画圆\"))"
  (if (null *DOC*)
    (progn
      (if (null base:init) (require 'base))
      (base:init)))
  (setq input (car param2))
  (if (> (@::max-char input) 127)
    (or
      (@::cmd-match-direct input)
      (@::cmd-match-menu input)
      (@::cmd-match-fuzzy input)
      (@::cmd-match-web input)
      (@::cmd-match-cloud-nlp input)
      (@::cmd-ai-fallback input))))


;; ── sub-system/condition/reactor.lsp ──────────────────────────────────────────
;; @depends base-function config-manager condition-nlp
;; @provides condition-reactor
(vl-load-com)
(defun @::enable-mouse-reactor ()
  (if (null @::*react-mouse*)
    (setq @::*react-mouse* (vlr-mouse-reactor nil '((:vlr-beginDoubleClick . @::dbclicked))))
    (vlr-add @::*react-mouse*)))
(defun @::disable-mouse-reactor ()
  (if @::*react-mouse*
    (vlr-remove @::*react-mouse*)))
(defun viewport-box (ent-vp)
  (list
    (list
      (-
        (car (entity:getdxf ent-vp 10))
        (* 0.5 (entity:getdxf ent-vp 40)))
      (-
        (cadr (entity:getdxf ent-vp 10))
        (* 0.5 (entity:getdxf ent-vp 41))))
    (list
      (+
        (car (entity:getdxf ent-vp 10))
        (* 0.5 (entity:getdxf ent-vp 40)))
      (+
        (cadr (entity:getdxf ent-vp 10))
        (* 0.5 (entity:getdxf ent-vp 41))))))
(defun pt-in-box? (pt box)
  (and
    (<
      (caar box)
      (car pt)
      (caadr box))
    (<
      (cadar box)
      (cadr pt)
      (cadadr box))))
(defun @::dbclicked (param1 param2 / aimrange vps vpsno1 vpmain flag flag2 *ACAD* *DOC* tmp-dbclick-ss)
  (setq *ACAD* (vlax-get-acad-object)
        *DOC*  (vla-get-ActiveDocument *ACAD*))
  (if
    (and
      (@::get-config '@::dbclicked-range)
      (<= 0.02 (@::get-config '@::dbclicked-range) 0.5))
    (setq aimrange (* 0.707 (getvar "viewsize") (@::get-config '@::dbclicked-range)))
    (setq aimrange (* 0.707 (getvar "viewsize") 0.1)))

  (if
    (and
      (null (ssget "c" (polar (car param2) (* 1.25 pi) aimrange) (polar (car param2) (* 0.25 pi) aimrange)))
      (or
        (= "Model" (getvar "ctab"))
        (progn
          (setq vps (pickset:to-list
                      (ssget
                        "x"
                        (list
                          '(0 . "viewport")
                          (cons 410 (getvar "ctab"))))))
          (setq vpsno1 (vl-remove-if
                         (function (lambda (x) (= 1 (entity:getdxf x 69))))
                         vps))
          (setq vpmain (car
                         (vl-remove-if-not
                           (function (lambda (x) (= 1 (entity:getdxf x 69))))
                           vps)))
          (setq flag nil)
          (setq flag2 nil)
          (foreach vp% vpsno1
            (if
              (pt-in-box?
                (car param2)
                (viewport-box vp%))
              (progn
                (setq flag2 t)
                (if (= 1 (entity:getdxf vp% 68))
                  (setq flag t)))))
          (if
            (and
              (null flag2)
              (= 1 (entity:getdxf vpmain 68)))
            (setq flag t))
          flag)))
    (progn
      (cond
        ((@::platform-is-linux-p)
         (setq tmp-dbclick-ss (cadr (ssgetfirst)))
         (command (chr 27))
         (@::panel-dialog))
        (is-bricscad
         (vla-postcommand (strcat "(C:@@) ")))
        (t
         (setq tmp-dbclick-ss (cadr (ssgetfirst)))
         (vla-postcommand *DOC* (strcat (chr 27) "@@ "))
         ;;(@::panel-dialog)
        ))
      ;; 遍历用户注册的双击回调
      (foreach hook @::*dbclick-hooks*
        (hook (car param2))))))


;; ── sub-system/cache.lsp ──────────────────────────────────────────
;; @depends base-function file-utils
;; @provides cache
(in-package :@)
(use-package :autolisp)

;; ============ @lisp Offline Cache Subsystem ============
;; Provides caching for network resources so @lisp can
;; function in limited or no connectivity environments.

;; ============ Cache Directory Setup ============

(setq @::*cache-dir* (strcat @::*prefix* ".cache/"))

(defun @::cache-ensure-dirs (/ dir)
  (foreach dir (list @::*cache-dir*
      (strcat @::*cache-dir* "modules/")
      (strcat @::*cache-dir* "meta/")
      (strcat @::*cache-dir* "locale/")
      (strcat @::*cache-dir* "packages/"))
    (if (null (findfile dir))
      (vl-mkdir dir))))

;; ============ Cache Core ============

(defun @::cache-timestamp ()
  (getvar "DATE"))

(defun @::cache-store (subdir key data ttl / dir fp mfp)
  ""
  (if (null (findfile @::*cache-dir*))
    nil
    (progn
      (setq dir (strcat @::*cache-dir* subdir "/"))
      (if (null (findfile dir)) (vl-mkdir dir))
      (setq fp (vl-catch-all-apply 'open (list (strcat dir key) "w")))
      (if (vl-catch-all-error-p fp)
        nil
        (progn
          (princ (vl-prin1-to-string data) fp)
          (close fp)
          (setq mfp (vl-catch-all-apply 'open (list (strcat dir key ".meta") "w")))
          (if (vl-catch-all-error-p mfp)
            (progn
              (vl-file-delete (strcat dir key))
              nil)
            (progn
              (princ (list (getvar "DATE") ttl) mfp)
              (close mfp)
              t)))))))

(defun @::cache-load (subdir key max-age / dir file mfile mfp meta saved-ts ttl content)
  (if (null (findfile @::*cache-dir*))
    nil
    (progn
      (setq dir (strcat @::*cache-dir* subdir "/"))
      (setq file (strcat dir key))
      (setq mfile (strcat dir key ".meta"))
      (if (findfile mfile)
        (progn
          (setq mfp (vl-catch-all-apply 'open (list mfile "r")))
          (if (not (vl-catch-all-error-p mfp))
            (progn
              (setq meta (read (read-line mfp)))
              (close mfp)
              (setq saved-ts (car meta))
              (setq ttl (cadr meta))
              (if (<= (@::cache-timestamp) (+ saved-ts (if max-age max-age ttl)))
                (progn
                  (setq content (vl-catch-all-apply 'read (list (vl-catch-all-apply '@::get-file-contents (list file)))))
                  (if (vl-catch-all-error-p content) nil content))
                (progn
                  (vl-file-delete file)
                  (vl-file-delete mfile)
                  nil)))
            nil))
         nil))))


(defun @::cache-invalidate (subdir key / dir f)
  (if (null (findfile @::*cache-dir*))
    nil
    (progn
      (setq dir (strcat @::*cache-dir* subdir "/"))
      (foreach f (list (strcat dir key) (strcat dir key ".meta"))
        (if (findfile f) (vl-file-delete f))))))

(defun @::cache-clear-all (/ subdirs dir f fullpath)
  (@::cache-ensure-dirs)
  (foreach subdir (vl-directory-files @::*cache-dir*)
    (setq dir (strcat @::*cache-dir* subdir "/"))
    (if (and (not (member subdir '("." "..")))
             (vl-file-directory-p dir))
      (foreach f (vl-directory-files dir)
        (setq fullpath (strcat dir f))
        (if (and (not (member f '("." "..")))
                 (not (vl-file-directory-p fullpath)))
          (vl-file-delete fullpath)))))
  (princ "All caches cleared.\n")
  (princ))


;; ── sub-system/scheduler.lsp ──────────────────────────────────────────
;; @depends base-function event-bus
;; @provides scheduler
(in-package :@)
(use-package :autolisp)
;; ============ @lisp Background Task Scheduler ============
;; Uses vlr-timer-reactor for periodic tasks without blocking CAD.
;; Falls back to command-reactor hooking for older CAD versions.
(setq @::*scheduler-tasks*              nil
      @::*scheduler-reactor*            nil
      @::*scheduler-interval-ms*        5000
      @::*scheduler-fallback-cmd-count* 0)
(defun @::schedule-task (name interval-sec handler oneshot / task)
  "注册定时任务。name: 唯一标识符; interval-sec: 执行间隔(s); handler: 无参函数; oneshot: 只执行一次"
  (setq task (list
               name
               interval-sec
               handler
               oneshot
                (or (getvar "TDUSERTIMER") (getvar "DATE") 0.0)))
  (setq @::*scheduler-tasks* (if (assoc name @::*scheduler-tasks*)
                               (subst
                                 task
                                 (assoc name @::*scheduler-tasks*)
                                 @::*scheduler-tasks*)
                               (cons task @::*scheduler-tasks*)))
  name)
(defun @::unschedule-task (name)
  "取消定时任务"
  (setq @::*scheduler-tasks* (vl-remove-if
                                 (function (lambda (task-item) (= (car task-item) name)))
                                @::*scheduler-tasks*))
  name)
(defun @::list-scheduled-tasks ()
  "列出所有注册的定时任务"
  (mapcar
    (function
      (lambda (task)
        (list (car task) (cadr task) (if (nth 3 task) "one-shot" "periodic") (nth 4 task))))
    @::*scheduler-tasks*))
(defun @::scheduler-once (name delay-sec handler)
  "注册一次性的延迟任务。执行后自动移除"
  (@::schedule-task name delay-sec handler t))
(defun @::scheduler-tick (/ now elapsed tasks-remaining task)
  "定时器滴答回调。遍历所有任务并执行到期的"
  (setq now             (or (getvar "TDUSERTIMER") (getvar "DATE") 0.0)
        tasks-remaining nil)
  (foreach task @::*scheduler-tasks*
    (setq elapsed (- now (nth 4 task)))
    (if (or (< (cadr task) 0) (>= elapsed (cadr task)))
      (progn
        (vl-catch-all-apply (nth 2 task) nil)
        (if (nth 3 task)
          (princ)
          (setq tasks-remaining (cons
                                  (list (car task) (cadr task) (nth 2 task) (nth 3 task) now)
                                  tasks-remaining))))
      (setq tasks-remaining (cons task tasks-remaining))))
  (setq @::*scheduler-tasks* (reverse tasks-remaining)))
(defun @::scheduler-timer-callback (reactor-orig data)
  "vlr-timer-reactor 回调"
  (@::scheduler-tick))
(defun @::scheduler-fallback-check ()
  "当 vlr-timer-reactor 不可用时的基于命令计数器的回退检查"
  (setq @::*scheduler-fallback-cmd-count* (1+ @::*scheduler-fallback-cmd-count*))
  (if (>= @::*scheduler-fallback-cmd-count* 10)
    (progn
      (setq @::*scheduler-fallback-cmd-count* 0)
      (@::scheduler-tick))))
(defun @::save-scheduler-tasks (/ fp path)
  "持久化定时任务列表到文件"
  (setq path (if @::*prefix-config* (strcat @::*prefix-config* "scheduler-tasks.dat")))
  (if path
    (progn
      (setq fp (vl-catch-all-apply 'open (list path "w")))
      (if (not (vl-catch-all-error-p fp))
        (progn
          (princ (vl-prin1-to-string @::*scheduler-tasks*) fp)
          (close fp))))))
(defun @::restore-scheduler-tasks (/ fp content path)
  "从文件恢复持久化的定时任务"
  (setq path (if @::*prefix-config* (strcat @::*prefix-config* "scheduler-tasks.dat")))
  (if path
    (progn
      (setq fp (vl-catch-all-apply 'open (list path "r")))
      (if (not (vl-catch-all-error-p fp))
        (progn
          (setq content (read (read-line fp)))
          (close fp)
          (if (listp content)
            (setq @::*scheduler-tasks* content)))))))
(defun @::enable-scheduler ()
  "启用定时调度器"
  (if (null @::*scheduler-reactor*)
    (not (vl-catch-all-error-p
           (vl-catch-all-apply
             (function (lambda ()
                (setq @::*scheduler-reactor* (vlr-timer-reactor
                                               @::*scheduler-interval-ms*
                                               (list (cons :vlr-timer '@::scheduler-timer-callback))))
                t))
             nil)))))
(defun @::disable-scheduler ()
  "禁用定时调度器"
  (if @::*scheduler-reactor*
    (progn
      (vlr-remove @::*scheduler-reactor*)
      (setq @::*scheduler-reactor* nil)))
  (setq @::*scheduler-tasks* nil))

;; ── sub-system/audit.lsp ──────────────────────────────────────────
;; @depends config-manager net file-utils base-function
;; @provides audit
;; @lisp Enterprise Audit Log System
;;
;; 服务端 API 依赖:
;;   POST /api/audit/log  -> (:result t)
;;     Body: JSON array of audit events
;;     Headers: Authorization: Bearer <token>
;;
;; 审计事件存储在本地 ~/.atlisp/audit/ 目录，
;; 定时批量推送到服务端。
(in-package :@)
(setq @::*audit-buffer* nil)
(setq @::*audit-max-buffer* 50)
(setq @::*audit-file* (strcat @::*prefix-config* "audit/"))
;; ═══════════════════════════════════════════════════════
;; 事件类型定义
;; ═══════════════════════════════════════════════════════
(defun @::audit-event-types ()
  '(:package.install :package.remove :package.upgrade :package.publish :config.change :config.sync :user.login
                     :user.logout :user.register :user.role-change :permission.denied :system.startup :system.upgrade :system.error
                     :enterprise.registry.change :sso.login :sso.logout))
;; ═══════════════════════════════════════════════════════
;; 核心审计函数
;; ═══════════════════════════════════════════════════════
(defun @::audit-log (event-type alist / user target value result detail)
  "记录审计事件。
  event-type: 事件类型符号，如 :package.install
  alist    — 关联列表：((:user . \"admin@co.com\") (:target . \"base\") ...)

      例: (@::audit-log :package.install
        (list (cons :user \"admin@co.com\")
            (cons :target \"base\")
              (cons :value \"1.2.0\")
                (cons :result :success)))"
  (setq user   (cdr (assoc :user alist))
        target (cdr (assoc :target alist))
        value  (cdr (assoc :value alist))
        result (cdr (assoc :result alist))
        detail (cdr (assoc :detail alist)))
  (if (> (@::get-config '@::audit-level) 0)
    ((lambda (event)
       (setq @::*audit-buffer* (append @::*audit-buffer* (list event)))
       (if (>= (length @::*audit-buffer*) @::*audit-max-buffer*)
         (@::audit-flush))
       event)
      (list
        (cons :timestamp (@::timestamp))
        (cons :event-type event-type)
        (cons :user (or user (@::get-config '@::user-email) "anonymous"))
        (cons :target (or target ""))
        (cons :value (or value ""))
        (cons :result (or result :success))
        (cons :detail (or detail ""))
        (cons :machineid (or @::*machineid* ""))
        (cons :version @::version)))))
(defun @::audit-flush (/ fp content)
  "将审计缓冲区写入本地文件并清空缓冲区"
  (if @::*audit-buffer*
    (progn
      (@::mkdir (@::path @::*audit-file*))
      (setq fp (vl-catch-all-apply
                 'open
                 (list (strcat @::*audit-file* (@::timestamp) ".json") "a")))
      (if (not (vl-catch-all-error-p fp))
        (progn
          (foreach event @::*audit-buffer*
            (write-line (vl-prin1-to-string event) fp))
          (close fp)))
      (setq @::*audit-buffer* nil))))
(defun @::audit-sync (/ events payload response)
  "将本地缓存的审计日志推送到服务端"
  (if
    (and
      (boundp '@::http-post)
      (eq 'subr (type @::http-post))
      (@::internetp)
      (/= "" (@::get-config '@::user-token)))
    (progn
      (setq events (@::audit-read-local))
      (if events
        (progn
          (setq payload (strcat
                          "{\"events\":["
                          (apply
                            'strcat
                            (mapcar
                              (function (lambda (e) (strcat (vl-prin1-to-string e) ",")))
                              (butlast events)))
                          (vl-prin1-to-string (car (last events)))
                          "]}"))
          (setq response (@::http-post
                           (strcat (@::uri) "/api/audit/log")
                           payload
                           "application/json"))
          (if (and response (cdr (assoc :result (json:parse response))))
            (progn
              (@::audit-clear-local)
              (@::@log "INFO" (strcat "Audit: synced " (itoa (length events)) " events")))
            (@::@log "WARN" "Audit sync failed")))))))
(defun @::audit-read-local (/ files events)
  "读取本地缓存的审计日志文件"
  (setq files (vl-directory-files @::*audit-file* "*.json" 1))
  (setq events nil)
  (foreach f files
    (@::with-file-lines
      (strcat @::*audit-file* f)
      (function (lambda (line) (setq events (cons (read line) events))))))
  (reverse events))
(defun @::audit-clear-local (/ files)
  "清除已同步的本地审计日志文件"
  (setq files (vl-directory-files @::*audit-file* "*.json" 1))
  (foreach f files
    (vl-file-delete (strcat @::*audit-file* f))))
(defun @::audit-query (event-type limit)
  "查询本地审计日志，按事件类型过滤"
  ((lambda (events result count)
     (setq limit (or limit 20))
     (foreach e (reverse events)
       (if (or (null event-type) (eq (cdr (assoc :event-type e)) event-type))
         (if (< count limit)
           (progn
             (setq result (cons e result))
             (setq count (1+ count))))))
     (reverse result))
    (@::audit-read-local)
    nil
    0))


;; ── sub-system/permission.lsp ──────────────────────────────────────────
;; -*- coding: utf-8 -*-
;; @depends config-manager net base-function
;; @provides permission
;; @lisp Enterprise Permission System (RBAC)
;; 角色层级: admin(100) > developer(80) > manager(60) > user(40) > viewer(20)
;;
;; 服务端 API 依赖:
;;   GET /api/user/role -> (:role :admin :permissions (...))
;;   POST /api/user/check-permission -> (:granted t)
(in-package :@)
(setq @::*role-hierarchy* '((:admin . 100) (:developer . 80) (:manager . 60) (:user . 40) (:viewer . 20)))
(setq @::*user-role* nil)
(setq @::*user-permissions* nil)
(defun @::role-weight (role)
  "获取角色的权重值"
  (cdr (assoc role @::*role-hierarchy*)))
(defun @::role-ge (role1 role2)
  "检查 role1 是否 >= role2"
  (>=
    (or (@::role-weight role1) 0)
    (or (@::role-weight role2) 0)))
;; ── 权限定义 ──────────────────────────────────────────
;; 每项: (permission-key required-role description)
(setq @::*permission-defs* '((:package.install :user "Install packages")
                              (:package.remove :manager "Remove packages")
                              (:package.upgrade :user "Upgrade packages")
                              (:package.publish :developer "Publish packages to registry")
                              (:package.lock :manager "Lock/unlock packages")
                              (:config.read :viewer "Read configuration")
                              (:config.write :manager "Modify configuration")
                              (:config.sync :user "Sync configuration to cloud")
                              (:user.login :viewer "Login")
                              (:user.register :viewer "Register new account")
                              (:user.manage :admin "Manage users (disable/suspend)")
                              (:audit.view :manager "View audit logs")
                              (:audit.export :admin "Export audit logs")
                              (:registry.read :viewer "Read package registry")
                              (:registry.write :developer "Write to package registry")
                              (:admin.access :admin "System administration access")))
(defun @::define-permission (key role desc)
  "定义新权限。第三方包可调用此函数注册自己的权限。"
  (if (not (assoc key @::*permission-defs*))
    (setq @::*permission-defs* (append @::*permission-defs* (list (list key role desc))))
    (@::@log "WARN" (strcat "Permission already defined: " (vl-symbol-name key)))))
(defun @::require-permission (permission-key)
  "检查当前用户是否有指定权限。返回 t 或 nil。
  如果用户未登录，默认仅允许 viewer 级权限。"
  ((lambda (perm required-role user-role)
     (if perm (setq required-role (cadr perm)))
     (if @::*user-role* (setq user-role @::*user-role*))
     (if (null perm)
       (progn
         (@::@log "WARN" (strcat "Unknown permission: " (vl-symbol-name permission-key)))
         nil)
       (@::role-ge user-role required-role)))
    (assoc permission-key @::*permission-defs*)
    :viewer
    :viewer))
(defun @::fetch-user-role (/ response)
  "从服务器获取当前用户角色和权限列表"
  (if
    (and
      (boundp '@::http-get)
      (eq 'subr (type @::http-get))
      (/= "" (@::get-config '@::user-token)))
    (progn
      (setq response (@::http-get (@::uri) (list "Authorization" (strcat "Bearer " (@::get-config '@::user-token)))))
      (if response
        (progn
          (setq response (json:parse response))
          (setq @::*user-role* (read (strcase (cdr (assoc "role" response)))))
          (setq @::*user-permissions* (mapcar 'read (cdr (assoc "permissions" response))))
          T))))
  (if (null @::*user-role*) (setq @::*user-role* :viewer))
  @::*user-role*)
(defun @::check-permission (permission-key)
  "带缓存的权限检查。先查本地缓存，再查服务器。"
  (if (member permission-key @::*user-permissions*)
    T
    (if (null @::*user-role*)
      (progn
        (@::fetch-user-role)
        (member permission-key @::*user-permissions*))
      (@::require-permission permission-key))))
(defun @::require-admin ()
  "检查是否为管理员"
  (@::require-permission :admin.access))


;; ── sub-system/config-sync/file.lsp ──────────────────────────────────────────
;; @depends base-function net config-manager
;; @provides config-sync-file
(setq @::*config-sync-items*
  '(@::autoupdate @::study-mode @::voice-mode @::speak-asynchronous
    @::speak-gender @::speak-volume @::speak-rate @::speak-voice
    @::shortcut @::dbclicked-panel @::dbclicked-range
    @::menu-curr-page @::menux-curr-page @::menu-per-page
    @::tips-currpage @::reactor-unknowcommand @::cmdline-prompts
    @::machine-translator @::draw-scale @::showPalette
    @::magnify @::num-precision @::text-baseheight @::funlib
    @::user @::user-email @::user-phone
    ;; Enterprise keys
    @::enterprise-registry @::sso-type @::sso-url @::sso-client-id
    @::audit-level @::audit-sync-interval))

;; ═══════════════════════════════════════════════════════
;; File sync — 跨设备同步用户文件（hotkey, config, pkg list）
;; 服务端 API:
;;   POST /api/user/sync/file/upload  上传文件
;;   GET  /api/user/sync/file/download 下载文件
;;   POST /api/user/sync/file/status  文件修改时间查询
;; ═══════════════════════════════════════════════════════

(setq @::*sync-files*
  '(("config.cfg"    . "config")       ;; 配置文件
    ("hotkey.cfg"    . "hotkey")       ;; 热键定义
    ("pkg-in-use.lst" . "packages"))   ;; 已安装包列表（含版本号）
)

(defun @::edittime-file ()
  "编辑时间记录文件路径"
  (strcat @::*prefix-config* ".edittime"))

(defun @::edittime-get (rel-path / key)
  "获取文件的本地编辑时间戳。返回 DATE 格式浮点数或 nil"
  (setq key (strcat rel-path ".edittime"))
  (if (findfile (@::edittime-file))
    ((lambda (et)
        (if (numberp et) et nil))
      (cdr (assoc key (read (@::get-file-contents (@::edittime-file))))))
    nil))

(defun @::edittime-set (rel-path / et-map key)
  "设置文件的本地编辑时间戳为当前时间"
  (setq key (strcat rel-path ".edittime"))
  (if (findfile (@::edittime-file))
    (setq et-map (read (@::get-file-contents (@::edittime-file))))
    (setq et-map nil))
  (if (assoc key et-map)
    (setq et-map (subst (cons key (getvar "DATE")) (assoc key et-map) et-map))
    (setq et-map (cons (cons key (getvar "DATE")) et-map)))
  ((lambda (fp)
      (if (not (vl-catch-all-error-p fp))
        (progn
          (print et-map fp)
          (close fp))))
    (vl-catch-all-apply 'open (list (@::edittime-file) "w"))))

(defun @::file-sync-status (/ results)
  "获取所有同步文件的本地状态列表"
  (setq results nil)
  (foreach pair @::*sync-files*
    ((lambda (rel-path full-path size exists)
        (setq exists (findfile full-path))
        (if exists
          (setq size (vl-file-size exists)))
        (setq results (cons
            (list
              (cons :path rel-path)
              (cons :edittime (@::edittime-get rel-path))
              (cons :size size)
              (cons :exists exists))
            results)))
      (car pair)
      (strcat @::*prefix-config* (car pair))
      0 nil))
  (reverse results))

(defun @::file-sync-push (rel-path / full-path content encoded)
  "将文件上传到服务端（base64 编码）"
  (setq full-path (strcat @::*prefix-config* rel-path))
  (if (findfile full-path)
    (progn
      (setq content (@::get-file-contents full-path))
      (if content
        ((lambda (response)
            (if (and response (cdr (assoc :result (read response))))
              (progn
                (@::@log "INFO" (strcat "File synced: " rel-path))
                t)
              (progn
                (@::@log "WARN" (strcat "File sync failed: " rel-path))
                nil)))
          (@::postjson
            (strcat (@::uri) "/api/user/sync/file/upload")
            (strcat "{\"path\":\"" rel-path
              "\",\"content\":\"" (if (boundp '@::base64-encode)
                (@::base64-encode content)
                content)
              "\",\"edittime\":" (rtos (or (@::edittime-get rel-path) 0) 2 6)
              ",\"machineid\":\"" @::*machineid* "\"}")
            (@::sync-headers))))
      nil)))

(defun @::file-sync-pull (rel-path / response content fp)
  "从服务端下载文件并覆盖本地"
  (setq response (@::http-get
      (strcat (@::uri) "/api/user/sync/file/download?path=" rel-path
        "&machineid=" @::*machineid*)
      (@::sync-headers)))
  (if (null response) nil
    (progn
      (setq response (json:parse response))
      (setq content (cdr (assoc "content" response)))
      (if (null content) nil
        (progn
          (setq fp (vl-catch-all-apply 'open (list (strcat @::*prefix-config* rel-path) "w")))
          (if (vl-catch-all-error-p fp) nil
            (progn
              (write-line content fp)
              (close fp)
              (@::edittime-set rel-path)
              (@::@log "INFO" (strcat "File pulled: " rel-path))
              t)))))))

(defun @::file-sync-direction (rel-path / server-edittime local-edittime direction)
  "判断同步方向: :push, :pull, :skip, :conflict"
  (setq local-edittime (@::edittime-get rel-path))
  (setq server-edittime
    ((lambda (response)
        (if response
          (cdr (assoc "edittime" (json:parse response)))
          nil))
      (@::postjson
        (strcat (@::uri) "/api/user/sync/file/status")
        (strcat "{\"path\":\"" rel-path "\",\"machineid\":\"" @::*machineid* "\"}")
        (@::sync-headers))))
  (cond
    ((null server-edittime) :push)           ;; 服务端无此文件 → 上传本地
    ((null local-edittime) :pull)             ;; 本地无记录 → 下载服务端
    ((> server-edittime local-edittime) :pull) ;; 服务端更新 → 下载
    ((< server-edittime local-edittime) :push)  ;; 本地更新 → 上传
    (t :skip)))                                ;; 一致 → 跳过

(defun @::file-sync-all (/ results)
  "同步所有文件，返回同步结果列表"
  (setq results nil)
  (foreach pair @::*sync-files*
    ((lambda (rel-path direction ok)
        (setq ok
          (cond
            ((eq direction :push) (@::file-sync-push rel-path))
            ((eq direction :pull) (@::file-sync-pull rel-path))
            (t t)))  ;; :skip
        (setq results (cons
            (list :path rel-path :action direction :result (if ok :success :failure))
            results)))
      (car pair)
      (@::file-sync-direction (car pair))
      nil))
  (reverse results))


;; ── sub-system/config-sync/config.lsp ──────────────────────────────────────────
;; @depends base-function net config-manager config-sync-file
;; @provides config-sync-config

;; ═══════════════════════════════════════════════════════
;; Existing sync functions
;; ═══════════════════════════════════════════════════════

(defun @::sync-url (path)
  (strcat (@::uri) "/api/user/sync" path
    "?_=" (@::timestamp)))
(defun @::sync-headers ()
  (list "Authorization" (strcat "Bearer " (@::get-config '@::user-token))))
(defun @::json-str (val)
  (cond
    ((eq 'int (type val)) (itoa val))
    ((eq 'real (type val)) (rtos val 2 10))
    (t (strcat "\"" val "\""))))
(defun @::json-build-array (items / result)
  (setq result nil)
  (foreach item items
    (setq result (cons (strcat "," item) result)))
  (if result
    (strcat "[" (substr (apply 'strcat (reverse result)) 2) "]")
    "[]"))
(defun @::config-sync-push (/ items item name val body)
  (setq items '())
  (foreach item @::*config-sync-items*
    (setq val (@::get-config item))
    (if (not (listp val))
      (setq items (cons
          (strcat "[" (@::json-str (vl-symbol-name item)) ","
            (@::json-str val) "]") items))))
  (setq body (@::json-build-array items))
  (@::postjson (@::sync-url "/config") (strcat "{\"config\":" body "}")
    (@::sync-headers)))
(defun @::config-sync-pull (/ response items item name val)
  (setq response (@::http-get (@::sync-url "/config") (@::sync-headers)))
  (if (and response (/= "" response))
    (progn
      (setq response (read response))
      (if (listp response)
        (progn
          (foreach item response
            (setq name (read (car item)))
            (if (member name @::*config-sync-items*)
              (@::set-config name (cdr item))))
          t)))
    nil))
(defun @::config-sync-packages-push (/ pkgs parts body)
  (setq pkgs @::*pkg-in-use* parts nil)
  (foreach pkg pkgs
    (setq parts (cons (strcat "[\"" pkg "\",\"\"]") parts)))
  (setq body (strcat "[" (apply 'strcat (reverse parts)) "]"))
  (@::postjson (@::sync-url "/packages") (strcat "{\"action\":\"sync\",\"packages\":" body "}")
    (@::sync-headers)))
(defun @::config-sync-changed-p (/ response last-sync)
  (setq response (@::http-get (@::sync-url "/status") (@::sync-headers)))
  (if response
    (progn
      (setq response (read response))
      (setq last-sync (@::get-config '@::last-sync-at))
      (or (null last-sync) (> response last-sync)))
    nil))
(defun @::config-sync-all (/ result ts)
  (setq result t)
  (if (@::config-sync-push)
    (@::@log "INFO" (strcat (_ "Config synced to cloud: ") (@::get-config '@::user-email)))
    (setq result nil))
  (if (@::config-sync-packages-push)
    (@::@log "INFO" (_ "Package list synced to cloud."))
    (setq result nil))
  (if (@::file-sync-all)
    (@::@log "INFO" (_ "Files synced to cloud."))
    (setq result nil))
  (if result
    (progn
      (setq ts (@::http-get (@::sync-url "/status") (@::sync-headers)))
      (@::set-config '@::last-sync-at
        (if (and ts (> (strlen ts) 0))
          (read ts)
          (getvar "DATE")))))
  result)
(defun C:@SYNC ()
  (if (and (@::valid-user) (/= "" (@::get-config '@::user-token)))
    (progn
      (princ "\n@lisp: ") (princ (_ "Syncing config to cloud..."))
      (if (@::config-sync-all)
        (progn
          (princ (_ "\n@lisp: Config sync complete."))
          (@::@log "INFO" (strcat "Sync completed: "
              (vl-prin1-to-string (@::file-sync-status)))))
        (progn
          (princ (_ "\n@lisp: Sync failed, check network."))
          (@::@log "ERROR" (_ "Config sync failed"))))
      (princ))
    (progn
      (princ (_ "\n@lisp: Please set user info first (C:@U) and get token."))
      (princ))))


;; ── sub-system/config/config.lsp ──────────────────────────────────────────
;; @depends config-manager i18n
;; @provides config
(setq @::*config-types* nil)
;; 断言: config/store.lsp 必须在此文件之前加载
(if (null (boundp '@::define-config-typed))
  (princ "\n*** FATAL: config.lsp 需要在 config/store.lsp 之后加载! 请检查 kernel-order.json ***\n"))
(@::load-locale "@lisp")
(if (null @::*i18n*)
    (progn
      (@::@log "WARN" "No locale files found, loading from local source.")
      (@::load-locale "@lisp")))
(@::define-config-typed '@::autoupdate 7 "Auto Upgrade. 0 not update, >0 Automatic update interval (in days)." 'int)
(@::define-config-typed '@::@debug-mode  0 "Debug mode,this mode will show more information. 1 file,2 file and screen." 'int)
(@::define-config-typed '@::study-mode 1 "Study mode: 0 closed, 1 tips in command line, 2 alert information." '(range 0 2))
(@::define-config-typed '@::f1 1 "Enable Command panel ACCELERATORS<F1>" 'bool)
(@::define-config-typed '@::dbclicked-panel  1 "Double click left key to show command panel" 'bool)
(@::define-config-typed '@::dbclicked-range 0.10 "Double click to display the blank range of the command panel, valid value: 0.02~0.5" '(range 0.02 0.5))
(@::define-config '@::shortcut "qa" "shortcut key to show command panel")
(@::define-config '@::user "anonymous" "User name for cloud or developement.")
(@::define-config '@::user-email "" "User's email for cloud or developement.")
(@::define-config '@::user-token "" "User's token, made from server.")
(@::define-config '@::user-phone "" "User's phone.")
(@::define-config '@::user-login-time "" "user login time")
(@::define-config '@::user-login-type "" "login type. wechat or email")
(@::define-config-typed '@::draw-scale 100 "Drawing scale." 'int)
(@::define-config-typed '@::menu-curr-page 0 "menu current page" 'int)
(@::define-config-typed '@::menux-curr-page 0 "all functions menu current page" 'int)
(@::define-config-typed '@::menu-per-page 8 "menus number of one page" '(range 1 50))
(@::define-config-typed '@::auto-mode 0 "auto execute programe. 1: No interaction, 0: interatcion." 'bool)
(@::define-config-typed '@::waitforresponse 1000 "network speed. 1000: common; 2000 slow ." '(range 100 10000))
(@::define-config-typed '@::tips-currpage 0 "@lisp tips current page." 'int)
(@::define-config-typed '@::funlib 1 "1: load funlib in boot. 0: not autoload funlib." 'bool)
(@::define-config-typed '@::undisturbed-mode 0 "Undisturbed mode" 'bool)
(@::define-config-typed '@::reactor-unknowcommand 1 "Handle unknown command" 'bool)
(@::define-config-typed '@::cmdline-prompts 1 "Command line prompts,1 Enable, 0 Disable." 'bool)
(@::define-config-typed '@::machine-translator 1 "Machine translation,1 Enable, 0 Disable." 'bool)
(@::define-config-typed '@::showPalette 1 "Show palettes at startup" 'bool)
(@::define-config-typed '@::voice-mode 5 "voice mode, 0 Disable voice,1 Process prompts, 2 Help,4 Chat " 'int)
(@::define-config-typed '@::speak-asynchronous 1 "Speaker. 1 asynchronous; 0 synchronous" 'bool)
(@::define-config '@::speak-gender "Female" "Speaker gender,Male or Female")
(@::define-config-typed '@::speak-volume 50 "Speaker volumn: 0-100" '(range 0 100))
(@::define-config-typed '@::speak-rate 2 "Speaker rate, 0 normal, -10 ~ 10" '(range -10 10))
(cond
 ((wcmatch @::*locale* "chs,zh*")
  (@::define-config-typed '@::speak-voice 0 "Speaker voice, 0 Mandarin, 1 Cantonese" '(range 0 1)))
 ((wcmatch @::*locale* "cht")
  (@::define-config-typed '@::speak-voice 1 "Speaker voice, 0 Mandarin, 1 Cantonese" '(range 0 1)))
 )
(@::define-config-typed '@::magnify 1.0 "The magnification level of the window. " '(range 0.1 10))
(@::define-config-typed '@::num-precision 3 "Numerical accuracy when displayed as text" '(range 0 8))

(@::define-config-typed '@::show-wizard 1 "Show setup wizard at startup (0=disabled)" 'bool)
(@::define-config-typed '@::text-baseheight 2.5 "The font base height when creating text" '(range 0.1 100))

;; ═══════════════════════════════════════════════════════
;; Enterprise configuration keys
;; ═══════════════════════════════════════════════════════
(@::define-config '@::enterprise-registry "" "Enterprise private package registry URL. e.g. https://registry.mycompany.com")
(@::define-config '@::enterprise-token "" "Enterprise authentication token for private registry access.")
(@::define-config '@::enterprise-ssl-verify 1 "Verify SSL certificate for enterprise registry. 1=verify, 0=skip.")
(@::define-config '@::sso-type 0 "Single Sign-On type: 0=disabled, 1=LDAP, 2=SAML, 3=OIDC")
(@::define-config '@::sso-url "" "SSO provider URL for enterprise login.")
(@::define-config '@::sso-client-id "" "SSO client ID for enterprise login.")
(@::define-config '@::audit-level 0 "Audit logging level: 0=off, 1=errors, 2=important, 3=all")
(@::define-config '@::audit-sync-interval 300 "Audit log sync interval in seconds (default: 300 = 5 min)")


;; ── sub-system/command.lsp ──────────────────────────────────────────
;; @depends config base-function
;; @provides command
(defpackage
  :C
  (:use :cl)
  (:export :@@W :@ :atlisp :@1 :@C :@F :@W :@H :@T :@X :@@ :@AI :@DIAG))
(in-package :C)
(defun C:@W ()
  (if (@::internetp)
    (@::browser)
    (@::alert (_ "Network unavailable."))))
(defun C:@F (/ ok req)
  "Force repair current @lisp environment"
  (vl-load-com)
  (setq ok (vl-catch-all-apply
             (function
               (lambda (/ req resp boot)
                 (setq req (vlax-create-object @::*winhttp-progid*))
                 (vlax-invoke
                   req
                   'OPEN
                   "GET"
                   (strcat "https://atlisp.cn/boot")
                   :vlax-false)
                 (vlax-invoke req 'SetRequestHeader "User-Agent" "Atlisp-User")
                 (vlax-invoke req 'Send)
                 (vlax-invoke req 'WaitforResponse @::*winhttp-timeout*)
                 (if (= @::*http-status-ok* (vlax-get-property req 'status))
                   (progn
                     (setq resp (vlax-get-property req 'ResponseText))
                     (vlax-release-object req)
                     (setq boot (read resp))
                     (if (listp boot)
                       (progn
                         (@::safe-eval boot)
                         (princ "\nBootstrap loaded from cloud.")
                         t)
                       (princ "\nInvalid bootstrap response.")))
                   (progn
                     (vlax-release-object req)
                     nil))))))
  (if
    (and
      (not (vl-catch-all-error-p ok))
      ok
      (boundp '@::internetp)
      (@::internetp))
    (progn
      (if (boundp '@::cache-clear-all)
        (@::cache-clear-all))
      (@::load-module 'network)
      (@::load-module 'pkgman)
      (@::@log "INFO" "Starting repair...")
      (if (and base:init (base:init) (@::upgrade))
        (@::@log "INFO" "Repair complete.")
        (@::@log "WARN" "Repair failed."))
      (princ (strcat "\n" (_ "@lisp environment repaired."))))
    (princ "\nRepair unavailable."))
  (princ))
(defun C:@H () (@::showCopyRight))
(defun C:@T () (@::load-module 'tips) (@::tips-dialog))
(defun C:@V () (@::phone))
(defun C:@@W (/ uri tmp-uri)
  (setvar "cmdecho" 0)
  (setq uri     "https://gitee.com/atlisp"
        tmp-uri (vl-bb-ref '@::tmp-uri))
  (if
    (and
      (eq 'str (type-of tmp-uri))
      (wcmatch tmp-uri (strcat uri "*")))
    (@::cmd "start" tmp-uri)
    (@::cmd "start" uri))
  (setvar "cmdecho" 1))
(defun C:@ () (@))
(defun C:atlisp () (@))
(defun C:@1 () (if (findfile (@::fasext "@lisp")) (load "@lisp")) (@::init-once))
(defun C:@@ () (@::panel-dialog))
(defun C:@C ()
  "@lisp chat"
  (if
    (and
      (@::internetp)
      (@::load-module 'pkgman)
      (@::load-module 'aibot))
    (@::chat-loop)
    (prompt (_ "Network unavailable."))))
(defun C:@G ()
  "@lisp GB palette"
  (if
    (and
      (@::internetp)
      (@::load-module 'aibot))
    (@::datawarehouse)
    (prompt (_ "Network unavailable."))))
(defun C:@AI (/ choice)
  "@lisp AI — 代码生成 / Agent / 聊天"
  (initget "CodeGen Agent Chat")
  (setq choice (getkword
    (strcat "\n@lisp AI [" (_ "CodeGen") "/" (_ "Agent") "/" (_ "Chat") "] <"
      (_ "CodeGen") ">: ")))
  (cond
    ((or (= choice "CodeGen") (null choice))
     (if (@::internetp)
       (progn
         (@::load-module 'aibot)
         (@::load-module 'ai-codegen)
         (@::ai-codegen-main))
       (prompt (strcat "\n" (_ "Network unavailable.") "\n"))))
    ((= choice "Agent")
     (if (@::load-module 'agent-client)
       (@::agent-menu)
       (prompt "Failed to load agent-client module.")))
    ((= choice "Chat")
     (C:@C))))
(defun C:@BATCH ()
  "@lisp batch DWG processor"
  (if (@::load-module 'batch)
    (@::batch-menu)
    (prompt "Failed to load batch module.")))
(defun C:@SK ()
  "@lisp skill library"
  (if (@::load-module 'skill)
    (@::skill-menu)
    (prompt "Failed to load skill module.")))
(defun C:@K ()
  "@lisp clear cache"
  (@::cache-clear-all))
(defun C:@CN (/ input result)
  "@lisp 中文命令入口 — 输入中文直接匹配命令或安装对应包"
  (setq input (getstring t (strcat "\n" (_ "Please input Chinese command") ": ")))
  (if (/= "" input)
    (if (and (boundp 'parse-cmdunknown) (eq 'subr (type parse-cmdunknown)))
      (parse-cmdunknown nil (list input))
      (princ (strcat "\n" (_ "Chinese command not available. Use C:@H for help.") "\n")))))
(defun C:@DIAG (/ damaged)
  "@lisp 完整性诊断 \u2014 检查 @::load-module 依赖链"
  (setq damaged (@::check-module-integrity))
  (if damaged
    (progn
      (princ (strcat "\n** " (_ "@lisp @::load-module 完整性诊断") " **\n"))
      (princ (strcat (_ "以下函数已被损坏") ":\n"))
      (foreach pair damaged
        (princ (strcat "  " (vl-symbol-name (car pair)) " -> " (symbol-name (cdr pair)) "\n")))
      (princ (strcat "\n" (_ "建议") ":\n"))
      (princ (strcat "  - " (_ "vlax-* 函数损坏: 执行 (vl-load-com)") "\n"))
      (princ (strcat "  - " (_ "@::* 函数损坏: 执行 (@) 重新加载 @lisp") "\n"))
      (princ (strcat "  - " (_ "核心 CAD 函数损坏: 重启 CAD") "\n")))
    (princ (strcat "\n** @lisp " (_ "完整性诊断: 所有函数正常") " **\n")))
  (princ))

;; ── init/compat.lsp ──────────────────────────────────────────
;; @depends command setup bootstrap
;; @provides init-compat
(defpackage
  :theme
  (:use :cl)
  (:export :bg-color))
(use-package :autolisp)
#-sbcl
(progn
  (set '@:load @::@load)
  (set '@:log @::@log)
  (set '@:debug @::@debug))
(defun @::compat1 (/ sym-name)
  "兼容性处理：创建单冒号别名，如 @::fun → @:fun"
  (if @::*compat1-done*
    nil
    (progn
      (setq @::*compat1-done* t)
      (foreach fun
        (vl-remove-if-not
          (function (lambda (x) (wcmatch (vl-prin1-to-string x) "*::*")))
          (atoms-family 0))
        (setq sym-name (vl-string-subst ":" "::" (vl-prin1-to-string fun)))
        (if (null (vl-catch-all-apply '@::safe-eval (list (read sym-name))))
          (set (read sym-name) (vl-catch-all-apply '@::safe-eval (list fun)))))))
(set 'compat1 @::compat1)
;; 兼容旧版本，避免函数名冲突
(defun @::load-local-pkg ()
  "加载本地包列表"
  (if
    (findfile
      (setq @::*file-pkg-in-use* (strcat @::*prefix-config* "pkg-in-use.lst")))
    (progn
      (setq @::*pkg-in-use* (vl-remove
                              ""
                              (mapcar
                                (function
                                  (lambda (line / pos)
                                    (if (setq pos (vl-string-search " " line))
                                      (substr line 1 pos)
                                      line)))
                                (@::string-to-list
                                  (@::get-file-contents @::*file-pkg-in-use*)
                                  "\n"))))
      (foreach pkg% @::*pkg-in-use*
        (if (/= "" pkg%)
          (set (read (strcat ":" pkg%)) (read (strcat ":" pkg%))))))
    (setq @::*pkg-in-use* '()))
  (mapcar
    (function
      (lambda (package)
        (if
          (and
            (eq 'str (type-of package))
            (/= "" package))
          (@::load-pkg package '()))))
    @::*pkg-in-use*))
(defun @::load-custom (/ custom-lsp custom-dir files exts)
  "加载自定义函数库 — 单次目录扫描，内存过滤后缀"
  (setq custom-lsp (strcat @::*prefix* "custom.lsp")
        custom-dir (strcat @::*prefix* "custom"))
  (if (findfile custom-lsp)
    (load custom-lsp "failure"))
  (if (findfile custom-dir)
    (progn
      (setq files (vl-directory-files custom-dir nil 1)
            exts  (if is-zwcad '("lsp" "zelx" "vls") '("lsp" "fas" "vlx")))
      (foreach f files
        (if (member (vl-filename-extension f) exts)
          (load (strcat "custom/" f) "failure")))))))


;; ── init/steps.lsp ──────────────────────────────────────────
;; @depends base-function net config-manager init-compat
;; @provides init-steps
;; ═══════════════════════════════════════════════════════
;; @::init-once — 按步骤拆分为独立函数
;; ═══════════════════════════════════════════════════════
(defun @::init-repair ()
  "Step 1: 最小化系统自我修复"
  (if
    (and
      (null (findfile "flag-nomnl"))
      (null (findfile "@lisp.mnl")))
    (@::install)
    (if (null (menugroup "@lisp")) (@::make-menu))))
(defun @::init-core (/ font-file)
  "Step 2: 核心环境 — MachineID/主题/字体"
  (if (boundp 'anti-crack) (anti-crack))
  (@::restore-mid)
  (@::load-mt)
  (if @::*machineid*
    (progn
      (setq theme::*bg-color* (fix (rem (apply '+ (s2l @::*machineid*)) 256)))
      (if (or (= 7 theme::*bg-color*) (= 255 theme::*bg-color*))
        (setq theme::*bg-color* 182)))
    (setq theme::*bg-color* 182))
  (set 'theme::bg-color theme::*bg-color*) ;; 兼容旧版
  (setq font-file (findfile "Fonts/simsum.ttc"))
  (if (and font-file (null (findfile (strcat font-file ".bak"))))
    (vl-file-rename font-file (strcat font-file ".bak"))))
(defun @::init-config ()
  "Step 3: 加载函数库"
  (@::@log "INFO" "Loading @lisp ...")
  (@::@log "INFO" (strcat "version: " @::*version*))
  (@::loadlib)
  (if base:init
    (base:init)
    (@::@log "WARN" "function lib not load!!!")))
(defun @::init-packages ()
  "Step 4: 加载锁定状态 + 本地包 + 锁定检查"
  (@::load-pkg-lock-states)
  (@::load-local-pkg)
  (@::pkg-lock-check)
  (@::init-config-file))
(defun @::init-config-file ()
  "Step 4b: 加载配置文件，覆盖包默认值"
  (vl-catch-all-apply
    (function (lambda ()
       (setq @::*config-db* (@::load-config))
       (if (> (@::get-config '@::auto-mode) 0)
         (setq @::*auto-mode* t))))
    nil)
  (if (null @::*config-db*)
    (setq @::*config-db* @::*config-default*)))
(defun @::init-hotkeys ()
  "Step 5: 热键 + 计时报告 + 启动事件"
  (setq @::*waitforresponse* (@::get-config '@::waitforresponse))
  (setq @::*pkg-in-use* @::*pkg-state*)
  ;; 仅在包列表有变化时才写文件
  (if (null (findfile (strcat @::*prefix-config* "pkg-in-use.lst")))
    (@::save-pkg-in-use))
  (@::load-hotkey)
  (setvar "filedia" 1)
  (@::set-hotkey (@::get-config '@::shortcut) '(@::panel-dialog))
  (setq @::*bootstrap-state* t)
  (vl-catch-all-apply
    (function (lambda () (@::event-emit 'startup-complete (list @::version @::*machineid*))))
    nil)
  (vl-catch-all-apply
    (function (lambda ()
       (@::audit-log
         :system.startup
         (list (cons :version @::version) (cons :machineid @::*machineid*)))))
    nil))
(defun @::prefetch-cache ()
  "后台预取常用数据到本地缓存，加速后续操作"
  (if (and (= 1 (vl-bb-ref '@::netstate)) (null (@::offline-mode-p)))
    (progn
      (if @::package-update
        (vl-catch-all-apply '@::package-update nil))
      (if (member 'function @::*modules*)
        (vl-catch-all-apply 'fun::prefetch-help nil)))))
(defun @::init-checks ()
  "Step 6: 网络探测/命令反应器/版本检查/缓存预热"
  (if (null (vl-bb-ref '@::netstate))
    (if (@::internetp)
      (progn
        (if
          (vl-catch-all-error-p
            (vl-catch-all-apply (function (lambda () (@::uri))) nil))
          nil)
        (if (or (null (@::uri)) (= "http://localhost:8100" (@::uri)))
          (@::proxy)))))
  (if (and (= 1 (vl-bb-ref '@::netstate)) (null (@::offline-mode-p)))
    (progn
      (@::load-module 'network)
      (if (null @::*machineid*)
        (vl-catch-all-apply
          (function (lambda ()
             (setq @::*machineid* (@::get-machineid))))
          nil))))
  (if (string-equal @::progname "atlisp")
    (@::load-module 'pkgman))
  (if (= 1 (@::get-config '@::reactor-unknowcommand))
    (@::enable-command-reactor)
    (@::disable-command-reactor))
  (if (null (@::check-new-version (@::get-config '@::autoupdate)))
    (progn
      (@::load-custom)
      (@::prefetch-cache)
      (if (= 1 (@::get-config '@::dbclicked-panel))
        (@::enable-mouse-reactor)
        (@::disable-mouse-reactor)))
    (@::upgrade-mini-sys)))


;; ── init/sequence.lsp ──────────────────────────────────────────
;; @depends base-function init-steps
;; @provides init-sequence
(defun @::with-timeout (seconds fn / start result)
  "带超时保护的函数执行器。超过秒数则跳过。"
  (setq start (getvar "MILLISECS"))
  (setq result (vl-catch-all-apply fn nil))
  (if (vl-catch-all-error-p result)
    nil
    (if (and (numberp start) (getvar "MILLISECS"))
      (if (>= (- (getvar "MILLISECS") start) (* seconds 1000))
        (progn
          (@::@log "WARN" (strcat "Step timed out (>" (itoa seconds) "s), skipping"))
          nil)
        result)
      result)))
(defun @::init-once (/ end-time usetime)
  "初始化入口 — 6 步独立函数，每步有超时保护"
  (cond
    (@::*bootstrap-state*)
    ((< @::*max-init-times* @::*init-times*)
     (princ (_ "There are too many attempts to repair to complete self repair."))
     (princ "\n"))
(t
       (setq start-time (getvar "MILLISECS"))
       (vl-catch-all-apply '@::init-repair nil)
       (vl-catch-all-apply '@::init-core nil)
       (vl-catch-all-apply '@::init-config nil)
       (@::with-timeout 30 '@::init-packages)
      (if (= @::*flag-damage* 1)
       (progn
         (setq @::*init-times*  (1+ @::*init-times*)
               @::*flag-damage* 0)
         (@::init))
        (progn
          (@::with-timeout 15 '@::init-hotkeys)
          (@::with-timeout 30 '@::init-checks)
         (setq end-time (if (getvar "MILLISECS")
                          (getvar "MILLISECS")
                          (getvar "TDUSRTIMER"))
               usetime  (if (and (numberp end-time) (numberp start-time))
                          (- end-time start-time)
                          0.8))
         (@::@log
           "INFO"
           (strcat
             "... @LISP "
             (_ "all packages loaded completed!!!")
             (_ "execute time")
             " "
             (rtos
               (if (> usetime 1) (* 0.001 usetime) (* @::*seconds-per-day* usetime))
               2
               3)
             " s\n"))
         (princ))))))
(defun @::init ()
  "初始化入口 — 6 步独立函数"
  (setq @::*bootstrap-state* nil)
  (@::init-once))
(@::compat1)
T
