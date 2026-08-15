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