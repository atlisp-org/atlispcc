;; CAD 手动测试脚本 - 加载各个测试 FAS 并验证
;; 用法: (load "C:/Users/vitalgg/atlisp/atlispcc/tests/cad_test_all.lsp")

(princ "\n=== CAD FAS Test Script ===\n")

;; 测试 1: 简单函数 (fun_our.fas)
(princ "\n[1/8] Loading fun_our.fas...")
(load "C:/Users/vitalgg/atlisp/atlispcc/tests/fun_our.fas" "\n  FAILED to load")
(if a (progn (princ "\n  OK: fun_our.fas loaded, calling (a)...") (a)))

;; 测试 2: 多函数 (multi_our.fas)
(princ "\n[2/8] Loading multi_our.fas...")
(load "C:/Users/vitalgg/atlisp/atlispcc/tests/multi_our.fas" "\n  FAILED to load")
(if add (princ "\n  OK: multi_our.fas loaded, (add 2 3) = "))
(if add (princ (add 2 3)))

;; 测试 3: cond 无 T 子句 (test_classify.fas)
(princ "\n[3/8] Loading test_classify.fas...")
(load "C:/Users/vitalgg/atlisp/atlispcc/tests/test_classify.fas" "\n  FAILED to load")
(if cad-classify (princ (strcat "\n  OK: (cad-classify 5) = " (cad-classify 5))))
(if cad-classify (princ (strcat "\n      (cad-classify 0) = " (cad-classify 0))))
(if cad-classify (princ (strcat "\n      (cad-classify -3) = " (cad-classify -3))))

;; 测试 4: is-prime (test_prime.fas) - 已知可能失败
(princ "\n[4/8] Loading test_prime.fas...")
(load "C:/Users/vitalgg/atlisp/atlispcc/tests/test_prime.fas" "\n  FAILED to load")
(if cad-is-prime (progn
  (princ "\n  OK: test_prime.fas loaded")
  (princ (strcat "\n      (cad-is-prime 7)  = " (itoa (if (cad-is-prime 7) 1 0))))
  (princ (strcat "\n      (cad-is-prime 10) = " (itoa (if (cad-is-prime 10) 1 0))))
  (princ (strcat "\n      (cad-is-prime 11) = " (itoa (if (cad-is-prime 11) 1 0))))
))

;; 测试 5: Progn-in-if-while (test_progn_if_while.fas)
(princ "\n[5/8] Loading test_progn_if_while.fas...")
(load "C:/Users/vitalgg/atlisp/atlispcc/tests/test_progn_if_while.fas" "\n  FAILED to load")
(if test-progn-if-while (progn
  (princ "\n  OK: test_progn_if_while.fas loaded")
  (princ (strcat "\n      (test-progn-if-while 5) = " (itoa (test-progn-if-while 5))))
))

;; 测试 6: 完整复杂文件 (cad_test_complex.fas)  
(princ "\n[6/8] Loading cad_test_complex.fas...")
(load "C:/Users/vitalgg/atlisp/atlispcc/tests/cad_test_complex.fas" "\n  FAILED to load")
(if cad-factorial (progn
  (princ "\n  OK: cad_test_complex.fas loaded")
  (princ (strcat "\n      (cad-factorial 5) = " (itoa (cad-factorial 5))))
  (princ (strcat "\n      (cad-fibonacci 8) = " (itoa (cad-fibonacci 8))))
  (princ (strcat "\n      (cad-sum-list '(1 2 3 4 5)) = " (itoa (cad-sum-list '(1 2 3 4 5)))))
  (princ (strcat "\n      (cad-str-repeat \"ab\" 3) = " (cad-str-repeat "ab" 3)))
  (princ (strcat "\n      (cad-gcd 48 18) = " (itoa (cad-gcd 48 18))))
  (princ (strcat "\n      (cad-classify -5) = " (cad-classify -5)))
  (princ (strcat "\n      (cad-classify 0) = " (cad-classify 0)))
  (princ (strcat "\n      (cad-classify 10) = " (cad-classify 10)))
  (princ (strcat "\n      (cad-foreach-sum '(10 20 30)) = " (itoa (cad-foreach-sum '(10 20 30)))))
  (princ (strcat "\n      (cad-apply-max '(3 7 1 9 4)) = " (itoa (cad-apply-max '(3 7 1 9 4)))))
))

;; 测试 7: 复杂文件 O2 优化 (cad_test_complex_O2.fas)  
(princ "\n[7/8] Loading cad_test_complex_O2.fas...")
(load "C:/Users/vitalgg/atlisp/atlispcc/tests/cad_test_complex_O2.fas" "\n  FAILED to load")

;; 测试 8: 简单 progn-in-if (test_progn_then.fas)
(princ "\n[8/8] Loading test_progn_then.fas...")
(load "C:/Users/vitalgg/atlisp/atlispcc/tests/test_progn_then.fas" "\n  FAILED to load")
(if test-progn-then (princ "\n  OK: test_progn_then.fas loaded"))

(princ "\n\n=== CAD Test Complete ===\n")
(princ)
