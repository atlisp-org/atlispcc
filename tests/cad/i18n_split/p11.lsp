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
