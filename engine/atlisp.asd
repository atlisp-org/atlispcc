;;;; atlisp.asd — AutoLISP runtime engine (SBCL)
(defpackage #:atlisp-system (:use #:cl))
(in-package #:atlisp-system)

(asdf:defsystem "atlisp"
  :description "AutoLISP runtime engine for CAD MCP (SBCL interpreter)"
  :version "0.1.0"
  :author "atlisp"
  :license "MIT"
  :depends-on ("uiop")
  :serial t
  :components
  ((:file "src/packages")
   (:file "src/values")
   (:file "src/reader")
   (:file "src/env")
   (:file "src/eval")
   (:file "src/builtins")
   (:file "src/main")))
