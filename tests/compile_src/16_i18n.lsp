;; 混合模式：顶层表达式 + defun + kwote + 中文
(setq @::*i18n* '()
      @::*lang* "zh_CN"
      @::*mt*   '())

(defun @::codepage2lang (codepage)
  "根据代码页返回语言标识符"
  (cdr
    (assoc
      codepage
      '(("ANSI_936" "zh" "zh_CN")
         ("ANSI_949" "kor" "kr")
         ("ANSI_1258" "vie" "vi")))))

(setq @::*codepage* "ANSI_936")

(if @::*codepage*
  (setq @::*mtlang* (car (@::codepage2lang @::*codepage*))
        @::*lang*   (cadr (@::codepage2lang @::*codepage*))))

(defun @::load-locale (pkg-name / fp opt%)
  (setq fp nil)
  (foreach opt% '(("a" "A") ("b" "B"))
    (if (eq pkg-name (car opt%))
      (setq fp (cdr opt%))))
  fp)

(defun @::translate (str / ret)
  (setq ret (cdr (assoc str @::*i18n*)))
  (if ret ret str))

(set '@::_ @::translate)
