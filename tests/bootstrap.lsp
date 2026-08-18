;; @depends platform version base-function
;; @provides bootstrap
;; 纯顶层 set/setq 绑定 + in-package/use-package 真实调用（CAD golden 对拍）。
(in-package :@)
(use-package :autolisp)
(setq @::progname "atlisp"
      $platform (getvar "platform")
      $userhome (getenv "HOME")
      @::*prefix* (strcat $userhome "/@lisp/"))
(setq @::*tmp-path* (strcat @::*prefix* "tmp/")
      @::*app-tmp-path* (strcat @::*prefix* "tmp/")
      @::*fingerprint-checksum* 246)
(set 'fasext (lambda (file) (strcat file @::*fasext*)))
(set 'vlx (lambda (file)
            (if (= ".fas" (substr file (- (strlen file) 4)))
              (setq file (strcat (substr file 1 (- (strlen file) 4)) ".fas"))
              file)))
(if (null @::*edition*) (setq @::*edition* "stable"))
