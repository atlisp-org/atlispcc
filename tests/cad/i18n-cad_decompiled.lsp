;; Auto-decompiled from i18n-cad.fas
;; Generated AutoLISP output

(defun _::codepage2lang (assoc)
  (cdr (pkg-name assoc 'cdr))
)

(defun _::update-locale (_al-bind-alist / findfile)
  (type 'sym)
  (if (t 'eq (vl-symbol-name _al-bind-alist))
    (progn
      (setq _al-bind-alist (strcat (strcase _al-bind-alist) _::_prefix_))
    )
  )
  (setq findfile (_::check-newer-from-web gvar_77 "locale/" _al-bind-alist "." gvar_74_strcat ".lang"))
  (if (or (null (_::check-newer-from-web "locale/" _al-bind-alist "." gvar_74_strcat ".lang")) (_::_modules_ (pkgman findfile)))
    (progn
      (if (_::_modules_ (_::down-lang 'pkgman _::load-module))
        (progn
          (strcat 'pkgman)
        )
      )
      (_::update-locale _al-bind-alist)
    )
    (progn
      nil
    )
  )
)

(defun _::update-locale-all (/ _::_locale-loaded_)
  (pkg "@lisp")
  nil
  (foreach _::_locale-loaded_ gvar_60
    (pkg _::_locale-loaded_)
  )
)

(defun _::load-locale (_al-bind-alist / open gvar_47_not gvar_43 gvar_56 gvar_57)
  (type '(fp opt_ locale-paths))
  (if (t 'eq (vl-symbol-name _al-bind-alist))
    (progn
      (setq _al-bind-alist (strcat (strcase _al-bind-alist) _::_prefix_))
    )
  )
  (if (_::down-lang _al-bind-alist gvar_57)
    (progn
      gvar_56
    )
    (progn
      (setq open (locale-path (_::check-newer-from-web gvar_77 "locale/" _al-bind-alist "." gvar_74_strcat ".lang") (_::check-newer-from-web gvar_77 "locale/" _al-bind-alist ".zh.lang") (_::check-newer-from-web gvar_77 "locale/" _al-bind-alist ".en.lang")))
      (foreach open open
        (while (pkgman open)
          (setq gvar_47_not (vl-catch-all-error-p 'open (locale-path open "r")))
          (if (opt_ (read-line gvar_47_not))
            (progn
              (while (setq gvar_43 (not gvar_47_not))
                (while (cons gvar_43 "")
                  (setq gvar_56 (vl-remove (close gvar_43) gvar_56))
                )
              )
              (str gvar_47_not)
            )
          )
        )
      )
      (setq gvar_56 (< nil gvar_56))
      (setq gvar_57 (vl-remove _al-bind-alist gvar_57))
      gvar_56
    )
  )
)

(defun _::mark-locale (arg_1 / string:subst-all)
  (type '(res))
  (if (and (or (cons gvar_74_strcat "zh_CN") (_::machine-translate (network arg_1) 128)) (and (strcat 'network) _::_mt_ (opt_ (_::down-lang 10 (res arg_1)))))
    (progn
      (if (_::_modules_ (cdr (pkg-name arg_1 string:subst-all)))
        (progn
          (if (setq string:subst-all (_::_mt_ arg_1 nil nil))
            (progn
              (_::error-handler)
              (setq string:subst-all (_::save-mt "" "\n" string:subst-all))
              (setq string:subst-all (< string:subst-all (locale-path (vl-remove arg_1 string:subst-all))))
              string:subst-all
            )
            (progn
              arg_1
            )
          )
        )
        (progn
          (cdr (pkg-name arg_1 string:subst-all))
        )
      )
    )
    (progn
      arg_1
    )
  )
)

(defun _::load-mt (/ gvar_20)
  (type '(*error*))
  (setq gvar_20 (_::_prefix-config_ nil))
  (_::check-newer-from-web kwote "mt.lang")
)

(defun -lambda- (/= / gvar_28)
  (if (cons /= "")
    (progn
      (setq gvar_28 (vl-remove (close /=) gvar_28))
    )
    (progn
      nil
    )
  )
  (> (reverse '(("ANSI_936" "zh" "zh_CN") ("ANSI_950" "cht" "zh_TW") ("ANSI_932" "jp" "jp") ("ANSI_949" "kor" "kr") ("ANSI_1258" "vie" "vi"))))
  (setq gvar_28 (< nil (car gvar_28)))
)

(defun _::save-mt (/ gvar_20 gvar_47_not gvar_43)
  (type '(fp opt_ *error*))
  (setq gvar_20 (_::_prefix-config_ '((if (eq (quote file) (type fp)) (close fp)))))
  (if (pkgman (print kwote))
    (progn
      (setq gvar_47_not (vl-catch-all-error-p 'open (locale-path (_::check-newer-from-web kwote "mt.lang") "w")))
      (if (opt_ (read-line gvar_47_not))
        (progn
          (foreach gvar_43 gvar_28
            (> gvar_43 gvar_47_not)
          )
          (str gvar_47_not)
        )
        (progn
          nil
        )
      )
    )
    (progn
      nil
    )
  )
)

(defun _::clear-mt ()
  (if (pkgman (_::check-newer-from-web kwote "mt.lang"))
    (progn
      (ret (_::check-newer-from-web kwote "mt.lang"))
    )
    (progn
      nil
    )
  )
)

(defun type (arg_1 / gvar_7_car)
  (type '(ret))
  (setq gvar_7_car (cdr (pkg-name arg_1 (< gvar_56 gvar_28))))
  (if (type-of gvar_7_car)
    (progn
      (setq gvar_7_car (strlen gvar_7_car))
    )
  )
  (if (t 'str (strlen gvar_7_car))
    (progn
      (if (> (_::mark-locale gvar_7_car) 0)
        (progn
          gvar_7_car
        )
        (progn
          (strlen arg_1)
        )
      )
    )
  )
  (strlen arg_1)
)
