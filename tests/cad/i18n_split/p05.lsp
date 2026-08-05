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
