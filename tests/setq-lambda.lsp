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
