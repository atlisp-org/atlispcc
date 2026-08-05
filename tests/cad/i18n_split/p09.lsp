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
