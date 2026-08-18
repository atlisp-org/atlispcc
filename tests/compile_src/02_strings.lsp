(defun greet (name)
  (princ (strcat "Hello, " name "!")))

(defun full-name (first last)
  (strcat first " " last))

(defun shout (s)
  (strcase (strcat s "!!")))
