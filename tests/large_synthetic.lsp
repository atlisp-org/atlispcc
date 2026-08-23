;; 大型合成 fixture（由 scripts/gen_large_fixture.py 生成，勿手改）。
;; 覆盖：nsyms>256 宽格式 USUBR/FUNC、多函数交叉引用、局部变量、
;; 顶层表达式、命令、变参。确定性内容：同一脚本输出逐字节一致。


(defun lgf-var-000 (lgf-var-000-a &optional lgf-var-000-opt &rest lgf-var-000-rest)
  (cons lgf-var-000-a (cons lgf-var-000-opt lgf-var-000-rest)))


(defun lgf-var-020 (lgf-var-020-a &optional lgf-var-020-opt &rest lgf-var-020-rest)
  (cons lgf-var-020-a (cons lgf-var-020-opt lgf-var-020-rest)))


(defun lgf-var-040 (lgf-var-040-a &optional lgf-var-040-opt &rest lgf-var-040-rest)
  (cons lgf-var-040-a (cons lgf-var-040-opt lgf-var-040-rest)))


(defun lgf-var-060 (lgf-var-060-a &optional lgf-var-060-opt &rest lgf-var-060-rest)
  (cons lgf-var-060-a (cons lgf-var-060-opt lgf-var-060-rest)))


(defun lgf-var-080 (lgf-var-080-a &optional lgf-var-080-opt &rest lgf-var-080-rest)
  (cons lgf-var-080-a (cons lgf-var-080-opt lgf-var-080-rest)))


(defun lgf-var-100 (lgf-var-100-a &optional lgf-var-100-opt &rest lgf-var-100-rest)
  (cons lgf-var-100-a (cons lgf-var-100-opt lgf-var-100-rest)))


(defun lgf-000 (a-000 b-000 / r-000 s-000)
  (setq r-000 (+ a-000 b-000))
  (setq s-000 (strcat (itoa r-000) " [%03d]"))
  (if (> r-000 100)
    (progn
      (setq r-000 (- r-000 100))
      (lgf-119 r-000 b-000))
    (lgf-001 r-000 a-000))
  (list a-000 b-000 r-000 s-000))


(defun lgf-001 (a-001 b-001 / r-001 s-001)
  (setq r-001 (+ a-001 b-001))
  (setq s-001 (strcat (itoa r-001) " [%03d]"))
  (if (> r-001 100)
    (progn
      (setq r-001 (- r-001 100))
      (lgf-000 r-001 b-001))
    (lgf-002 r-001 a-001))
  (list a-001 b-001 r-001 s-001))


(defun lgf-002 (a-002 b-002 / r-002 s-002)
  (setq r-002 (+ a-002 b-002))
  (setq s-002 (strcat (itoa r-002) " [%03d]"))
  (if (> r-002 100)
    (progn
      (setq r-002 (- r-002 100))
      (lgf-001 r-002 b-002))
    (lgf-003 r-002 a-002))
  (list a-002 b-002 r-002 s-002))


(defun lgf-003 (a-003 b-003 / r-003 s-003)
  (setq r-003 (+ a-003 b-003))
  (setq s-003 (strcat (itoa r-003) " [%03d]"))
  (if (> r-003 100)
    (progn
      (setq r-003 (- r-003 100))
      (lgf-002 r-003 b-003))
    (lgf-004 r-003 a-003))
  (list a-003 b-003 r-003 s-003))


(defun lgf-004 (a-004 b-004 / r-004 s-004)
  (setq r-004 (+ a-004 b-004))
  (setq s-004 (strcat (itoa r-004) " [%03d]"))
  (if (> r-004 100)
    (progn
      (setq r-004 (- r-004 100))
      (lgf-003 r-004 b-004))
    (lgf-005 r-004 a-004))
  (list a-004 b-004 r-004 s-004))


(defun lgf-005 (a-005 b-005 / r-005 s-005)
  (setq r-005 (+ a-005 b-005))
  (setq s-005 (strcat (itoa r-005) " [%03d]"))
  (if (> r-005 100)
    (progn
      (setq r-005 (- r-005 100))
      (lgf-004 r-005 b-005))
    (lgf-006 r-005 a-005))
  (list a-005 b-005 r-005 s-005))


(defun lgf-006 (a-006 b-006 / r-006 s-006)
  (setq r-006 (+ a-006 b-006))
  (setq s-006 (strcat (itoa r-006) " [%03d]"))
  (if (> r-006 100)
    (progn
      (setq r-006 (- r-006 100))
      (lgf-005 r-006 b-006))
    (lgf-007 r-006 a-006))
  (list a-006 b-006 r-006 s-006))


(defun lgf-007 (a-007 b-007 / r-007 s-007)
  (setq r-007 (+ a-007 b-007))
  (setq s-007 (strcat (itoa r-007) " [%03d]"))
  (if (> r-007 100)
    (progn
      (setq r-007 (- r-007 100))
      (lgf-006 r-007 b-007))
    (lgf-008 r-007 a-007))
  (list a-007 b-007 r-007 s-007))


(defun lgf-008 (a-008 b-008 / r-008 s-008)
  (setq r-008 (+ a-008 b-008))
  (setq s-008 (strcat (itoa r-008) " [%03d]"))
  (if (> r-008 100)
    (progn
      (setq r-008 (- r-008 100))
      (lgf-007 r-008 b-008))
    (lgf-009 r-008 a-008))
  (list a-008 b-008 r-008 s-008))


(defun lgf-009 (a-009 b-009 / r-009 s-009)
  (setq r-009 (+ a-009 b-009))
  (setq s-009 (strcat (itoa r-009) " [%03d]"))
  (if (> r-009 100)
    (progn
      (setq r-009 (- r-009 100))
      (lgf-008 r-009 b-009))
    (lgf-010 r-009 a-009))
  (list a-009 b-009 r-009 s-009))


(defun lgf-010 (a-010 b-010 / r-010 s-010)
  (setq r-010 (+ a-010 b-010))
  (setq s-010 (strcat (itoa r-010) " [%03d]"))
  (if (> r-010 100)
    (progn
      (setq r-010 (- r-010 100))
      (lgf-009 r-010 b-010))
    (lgf-011 r-010 a-010))
  (list a-010 b-010 r-010 s-010))


(defun lgf-011 (a-011 b-011 / r-011 s-011)
  (setq r-011 (+ a-011 b-011))
  (setq s-011 (strcat (itoa r-011) " [%03d]"))
  (if (> r-011 100)
    (progn
      (setq r-011 (- r-011 100))
      (lgf-010 r-011 b-011))
    (lgf-012 r-011 a-011))
  (list a-011 b-011 r-011 s-011))


(defun lgf-012 (a-012 b-012 / r-012 s-012)
  (setq r-012 (+ a-012 b-012))
  (setq s-012 (strcat (itoa r-012) " [%03d]"))
  (if (> r-012 100)
    (progn
      (setq r-012 (- r-012 100))
      (lgf-011 r-012 b-012))
    (lgf-013 r-012 a-012))
  (list a-012 b-012 r-012 s-012))


(defun lgf-013 (a-013 b-013 / r-013 s-013)
  (setq r-013 (+ a-013 b-013))
  (setq s-013 (strcat (itoa r-013) " [%03d]"))
  (if (> r-013 100)
    (progn
      (setq r-013 (- r-013 100))
      (lgf-012 r-013 b-013))
    (lgf-014 r-013 a-013))
  (list a-013 b-013 r-013 s-013))


(defun lgf-014 (a-014 b-014 / r-014 s-014)
  (setq r-014 (+ a-014 b-014))
  (setq s-014 (strcat (itoa r-014) " [%03d]"))
  (if (> r-014 100)
    (progn
      (setq r-014 (- r-014 100))
      (lgf-013 r-014 b-014))
    (lgf-015 r-014 a-014))
  (list a-014 b-014 r-014 s-014))


(defun lgf-015 (a-015 b-015 / r-015 s-015)
  (setq r-015 (+ a-015 b-015))
  (setq s-015 (strcat (itoa r-015) " [%03d]"))
  (if (> r-015 100)
    (progn
      (setq r-015 (- r-015 100))
      (lgf-014 r-015 b-015))
    (lgf-016 r-015 a-015))
  (list a-015 b-015 r-015 s-015))


(defun lgf-016 (a-016 b-016 / r-016 s-016)
  (setq r-016 (+ a-016 b-016))
  (setq s-016 (strcat (itoa r-016) " [%03d]"))
  (if (> r-016 100)
    (progn
      (setq r-016 (- r-016 100))
      (lgf-015 r-016 b-016))
    (lgf-017 r-016 a-016))
  (list a-016 b-016 r-016 s-016))


(defun lgf-017 (a-017 b-017 / r-017 s-017)
  (setq r-017 (+ a-017 b-017))
  (setq s-017 (strcat (itoa r-017) " [%03d]"))
  (if (> r-017 100)
    (progn
      (setq r-017 (- r-017 100))
      (lgf-016 r-017 b-017))
    (lgf-018 r-017 a-017))
  (list a-017 b-017 r-017 s-017))


(defun lgf-018 (a-018 b-018 / r-018 s-018)
  (setq r-018 (+ a-018 b-018))
  (setq s-018 (strcat (itoa r-018) " [%03d]"))
  (if (> r-018 100)
    (progn
      (setq r-018 (- r-018 100))
      (lgf-017 r-018 b-018))
    (lgf-019 r-018 a-018))
  (list a-018 b-018 r-018 s-018))


(defun lgf-019 (a-019 b-019 / r-019 s-019)
  (setq r-019 (+ a-019 b-019))
  (setq s-019 (strcat (itoa r-019) " [%03d]"))
  (if (> r-019 100)
    (progn
      (setq r-019 (- r-019 100))
      (lgf-018 r-019 b-019))
    (lgf-020 r-019 a-019))
  (list a-019 b-019 r-019 s-019))


(defun lgf-020 (a-020 b-020 / r-020 s-020)
  (setq r-020 (+ a-020 b-020))
  (setq s-020 (strcat (itoa r-020) " [%03d]"))
  (if (> r-020 100)
    (progn
      (setq r-020 (- r-020 100))
      (lgf-019 r-020 b-020))
    (lgf-021 r-020 a-020))
  (list a-020 b-020 r-020 s-020))


(defun lgf-021 (a-021 b-021 / r-021 s-021)
  (setq r-021 (+ a-021 b-021))
  (setq s-021 (strcat (itoa r-021) " [%03d]"))
  (if (> r-021 100)
    (progn
      (setq r-021 (- r-021 100))
      (lgf-020 r-021 b-021))
    (lgf-022 r-021 a-021))
  (list a-021 b-021 r-021 s-021))


(defun lgf-022 (a-022 b-022 / r-022 s-022)
  (setq r-022 (+ a-022 b-022))
  (setq s-022 (strcat (itoa r-022) " [%03d]"))
  (if (> r-022 100)
    (progn
      (setq r-022 (- r-022 100))
      (lgf-021 r-022 b-022))
    (lgf-023 r-022 a-022))
  (list a-022 b-022 r-022 s-022))


(defun lgf-023 (a-023 b-023 / r-023 s-023)
  (setq r-023 (+ a-023 b-023))
  (setq s-023 (strcat (itoa r-023) " [%03d]"))
  (if (> r-023 100)
    (progn
      (setq r-023 (- r-023 100))
      (lgf-022 r-023 b-023))
    (lgf-024 r-023 a-023))
  (list a-023 b-023 r-023 s-023))


(defun lgf-024 (a-024 b-024 / r-024 s-024)
  (setq r-024 (+ a-024 b-024))
  (setq s-024 (strcat (itoa r-024) " [%03d]"))
  (if (> r-024 100)
    (progn
      (setq r-024 (- r-024 100))
      (lgf-023 r-024 b-024))
    (lgf-025 r-024 a-024))
  (list a-024 b-024 r-024 s-024))


(defun lgf-025 (a-025 b-025 / r-025 s-025)
  (setq r-025 (+ a-025 b-025))
  (setq s-025 (strcat (itoa r-025) " [%03d]"))
  (if (> r-025 100)
    (progn
      (setq r-025 (- r-025 100))
      (lgf-024 r-025 b-025))
    (lgf-026 r-025 a-025))
  (list a-025 b-025 r-025 s-025))


(defun lgf-026 (a-026 b-026 / r-026 s-026)
  (setq r-026 (+ a-026 b-026))
  (setq s-026 (strcat (itoa r-026) " [%03d]"))
  (if (> r-026 100)
    (progn
      (setq r-026 (- r-026 100))
      (lgf-025 r-026 b-026))
    (lgf-027 r-026 a-026))
  (list a-026 b-026 r-026 s-026))


(defun lgf-027 (a-027 b-027 / r-027 s-027)
  (setq r-027 (+ a-027 b-027))
  (setq s-027 (strcat (itoa r-027) " [%03d]"))
  (if (> r-027 100)
    (progn
      (setq r-027 (- r-027 100))
      (lgf-026 r-027 b-027))
    (lgf-028 r-027 a-027))
  (list a-027 b-027 r-027 s-027))


(defun lgf-028 (a-028 b-028 / r-028 s-028)
  (setq r-028 (+ a-028 b-028))
  (setq s-028 (strcat (itoa r-028) " [%03d]"))
  (if (> r-028 100)
    (progn
      (setq r-028 (- r-028 100))
      (lgf-027 r-028 b-028))
    (lgf-029 r-028 a-028))
  (list a-028 b-028 r-028 s-028))


(defun lgf-029 (a-029 b-029 / r-029 s-029)
  (setq r-029 (+ a-029 b-029))
  (setq s-029 (strcat (itoa r-029) " [%03d]"))
  (if (> r-029 100)
    (progn
      (setq r-029 (- r-029 100))
      (lgf-028 r-029 b-029))
    (lgf-030 r-029 a-029))
  (list a-029 b-029 r-029 s-029))


(defun lgf-030 (a-030 b-030 / r-030 s-030)
  (setq r-030 (+ a-030 b-030))
  (setq s-030 (strcat (itoa r-030) " [%03d]"))
  (if (> r-030 100)
    (progn
      (setq r-030 (- r-030 100))
      (lgf-029 r-030 b-030))
    (lgf-031 r-030 a-030))
  (list a-030 b-030 r-030 s-030))


(defun lgf-031 (a-031 b-031 / r-031 s-031)
  (setq r-031 (+ a-031 b-031))
  (setq s-031 (strcat (itoa r-031) " [%03d]"))
  (if (> r-031 100)
    (progn
      (setq r-031 (- r-031 100))
      (lgf-030 r-031 b-031))
    (lgf-032 r-031 a-031))
  (list a-031 b-031 r-031 s-031))


(defun lgf-032 (a-032 b-032 / r-032 s-032)
  (setq r-032 (+ a-032 b-032))
  (setq s-032 (strcat (itoa r-032) " [%03d]"))
  (if (> r-032 100)
    (progn
      (setq r-032 (- r-032 100))
      (lgf-031 r-032 b-032))
    (lgf-033 r-032 a-032))
  (list a-032 b-032 r-032 s-032))


(defun lgf-033 (a-033 b-033 / r-033 s-033)
  (setq r-033 (+ a-033 b-033))
  (setq s-033 (strcat (itoa r-033) " [%03d]"))
  (if (> r-033 100)
    (progn
      (setq r-033 (- r-033 100))
      (lgf-032 r-033 b-033))
    (lgf-034 r-033 a-033))
  (list a-033 b-033 r-033 s-033))


(defun lgf-034 (a-034 b-034 / r-034 s-034)
  (setq r-034 (+ a-034 b-034))
  (setq s-034 (strcat (itoa r-034) " [%03d]"))
  (if (> r-034 100)
    (progn
      (setq r-034 (- r-034 100))
      (lgf-033 r-034 b-034))
    (lgf-035 r-034 a-034))
  (list a-034 b-034 r-034 s-034))


(defun lgf-035 (a-035 b-035 / r-035 s-035)
  (setq r-035 (+ a-035 b-035))
  (setq s-035 (strcat (itoa r-035) " [%03d]"))
  (if (> r-035 100)
    (progn
      (setq r-035 (- r-035 100))
      (lgf-034 r-035 b-035))
    (lgf-036 r-035 a-035))
  (list a-035 b-035 r-035 s-035))


(defun lgf-036 (a-036 b-036 / r-036 s-036)
  (setq r-036 (+ a-036 b-036))
  (setq s-036 (strcat (itoa r-036) " [%03d]"))
  (if (> r-036 100)
    (progn
      (setq r-036 (- r-036 100))
      (lgf-035 r-036 b-036))
    (lgf-037 r-036 a-036))
  (list a-036 b-036 r-036 s-036))


(defun lgf-037 (a-037 b-037 / r-037 s-037)
  (setq r-037 (+ a-037 b-037))
  (setq s-037 (strcat (itoa r-037) " [%03d]"))
  (if (> r-037 100)
    (progn
      (setq r-037 (- r-037 100))
      (lgf-036 r-037 b-037))
    (lgf-038 r-037 a-037))
  (list a-037 b-037 r-037 s-037))


(defun lgf-038 (a-038 b-038 / r-038 s-038)
  (setq r-038 (+ a-038 b-038))
  (setq s-038 (strcat (itoa r-038) " [%03d]"))
  (if (> r-038 100)
    (progn
      (setq r-038 (- r-038 100))
      (lgf-037 r-038 b-038))
    (lgf-039 r-038 a-038))
  (list a-038 b-038 r-038 s-038))


(defun lgf-039 (a-039 b-039 / r-039 s-039)
  (setq r-039 (+ a-039 b-039))
  (setq s-039 (strcat (itoa r-039) " [%03d]"))
  (if (> r-039 100)
    (progn
      (setq r-039 (- r-039 100))
      (lgf-038 r-039 b-039))
    (lgf-040 r-039 a-039))
  (list a-039 b-039 r-039 s-039))


(defun lgf-040 (a-040 b-040 / r-040 s-040)
  (setq r-040 (+ a-040 b-040))
  (setq s-040 (strcat (itoa r-040) " [%03d]"))
  (if (> r-040 100)
    (progn
      (setq r-040 (- r-040 100))
      (lgf-039 r-040 b-040))
    (lgf-041 r-040 a-040))
  (list a-040 b-040 r-040 s-040))


(defun lgf-041 (a-041 b-041 / r-041 s-041)
  (setq r-041 (+ a-041 b-041))
  (setq s-041 (strcat (itoa r-041) " [%03d]"))
  (if (> r-041 100)
    (progn
      (setq r-041 (- r-041 100))
      (lgf-040 r-041 b-041))
    (lgf-042 r-041 a-041))
  (list a-041 b-041 r-041 s-041))


(defun lgf-042 (a-042 b-042 / r-042 s-042)
  (setq r-042 (+ a-042 b-042))
  (setq s-042 (strcat (itoa r-042) " [%03d]"))
  (if (> r-042 100)
    (progn
      (setq r-042 (- r-042 100))
      (lgf-041 r-042 b-042))
    (lgf-043 r-042 a-042))
  (list a-042 b-042 r-042 s-042))


(defun lgf-043 (a-043 b-043 / r-043 s-043)
  (setq r-043 (+ a-043 b-043))
  (setq s-043 (strcat (itoa r-043) " [%03d]"))
  (if (> r-043 100)
    (progn
      (setq r-043 (- r-043 100))
      (lgf-042 r-043 b-043))
    (lgf-044 r-043 a-043))
  (list a-043 b-043 r-043 s-043))


(defun lgf-044 (a-044 b-044 / r-044 s-044)
  (setq r-044 (+ a-044 b-044))
  (setq s-044 (strcat (itoa r-044) " [%03d]"))
  (if (> r-044 100)
    (progn
      (setq r-044 (- r-044 100))
      (lgf-043 r-044 b-044))
    (lgf-045 r-044 a-044))
  (list a-044 b-044 r-044 s-044))


(defun lgf-045 (a-045 b-045 / r-045 s-045)
  (setq r-045 (+ a-045 b-045))
  (setq s-045 (strcat (itoa r-045) " [%03d]"))
  (if (> r-045 100)
    (progn
      (setq r-045 (- r-045 100))
      (lgf-044 r-045 b-045))
    (lgf-046 r-045 a-045))
  (list a-045 b-045 r-045 s-045))


(defun lgf-046 (a-046 b-046 / r-046 s-046)
  (setq r-046 (+ a-046 b-046))
  (setq s-046 (strcat (itoa r-046) " [%03d]"))
  (if (> r-046 100)
    (progn
      (setq r-046 (- r-046 100))
      (lgf-045 r-046 b-046))
    (lgf-047 r-046 a-046))
  (list a-046 b-046 r-046 s-046))


(defun lgf-047 (a-047 b-047 / r-047 s-047)
  (setq r-047 (+ a-047 b-047))
  (setq s-047 (strcat (itoa r-047) " [%03d]"))
  (if (> r-047 100)
    (progn
      (setq r-047 (- r-047 100))
      (lgf-046 r-047 b-047))
    (lgf-048 r-047 a-047))
  (list a-047 b-047 r-047 s-047))


(defun lgf-048 (a-048 b-048 / r-048 s-048)
  (setq r-048 (+ a-048 b-048))
  (setq s-048 (strcat (itoa r-048) " [%03d]"))
  (if (> r-048 100)
    (progn
      (setq r-048 (- r-048 100))
      (lgf-047 r-048 b-048))
    (lgf-049 r-048 a-048))
  (list a-048 b-048 r-048 s-048))


(defun lgf-049 (a-049 b-049 / r-049 s-049)
  (setq r-049 (+ a-049 b-049))
  (setq s-049 (strcat (itoa r-049) " [%03d]"))
  (if (> r-049 100)
    (progn
      (setq r-049 (- r-049 100))
      (lgf-048 r-049 b-049))
    (lgf-050 r-049 a-049))
  (list a-049 b-049 r-049 s-049))


(defun lgf-050 (a-050 b-050 / r-050 s-050)
  (setq r-050 (+ a-050 b-050))
  (setq s-050 (strcat (itoa r-050) " [%03d]"))
  (if (> r-050 100)
    (progn
      (setq r-050 (- r-050 100))
      (lgf-049 r-050 b-050))
    (lgf-051 r-050 a-050))
  (list a-050 b-050 r-050 s-050))


(defun lgf-051 (a-051 b-051 / r-051 s-051)
  (setq r-051 (+ a-051 b-051))
  (setq s-051 (strcat (itoa r-051) " [%03d]"))
  (if (> r-051 100)
    (progn
      (setq r-051 (- r-051 100))
      (lgf-050 r-051 b-051))
    (lgf-052 r-051 a-051))
  (list a-051 b-051 r-051 s-051))


(defun lgf-052 (a-052 b-052 / r-052 s-052)
  (setq r-052 (+ a-052 b-052))
  (setq s-052 (strcat (itoa r-052) " [%03d]"))
  (if (> r-052 100)
    (progn
      (setq r-052 (- r-052 100))
      (lgf-051 r-052 b-052))
    (lgf-053 r-052 a-052))
  (list a-052 b-052 r-052 s-052))


(defun lgf-053 (a-053 b-053 / r-053 s-053)
  (setq r-053 (+ a-053 b-053))
  (setq s-053 (strcat (itoa r-053) " [%03d]"))
  (if (> r-053 100)
    (progn
      (setq r-053 (- r-053 100))
      (lgf-052 r-053 b-053))
    (lgf-054 r-053 a-053))
  (list a-053 b-053 r-053 s-053))


(defun lgf-054 (a-054 b-054 / r-054 s-054)
  (setq r-054 (+ a-054 b-054))
  (setq s-054 (strcat (itoa r-054) " [%03d]"))
  (if (> r-054 100)
    (progn
      (setq r-054 (- r-054 100))
      (lgf-053 r-054 b-054))
    (lgf-055 r-054 a-054))
  (list a-054 b-054 r-054 s-054))


(defun lgf-055 (a-055 b-055 / r-055 s-055)
  (setq r-055 (+ a-055 b-055))
  (setq s-055 (strcat (itoa r-055) " [%03d]"))
  (if (> r-055 100)
    (progn
      (setq r-055 (- r-055 100))
      (lgf-054 r-055 b-055))
    (lgf-056 r-055 a-055))
  (list a-055 b-055 r-055 s-055))


(defun lgf-056 (a-056 b-056 / r-056 s-056)
  (setq r-056 (+ a-056 b-056))
  (setq s-056 (strcat (itoa r-056) " [%03d]"))
  (if (> r-056 100)
    (progn
      (setq r-056 (- r-056 100))
      (lgf-055 r-056 b-056))
    (lgf-057 r-056 a-056))
  (list a-056 b-056 r-056 s-056))


(defun lgf-057 (a-057 b-057 / r-057 s-057)
  (setq r-057 (+ a-057 b-057))
  (setq s-057 (strcat (itoa r-057) " [%03d]"))
  (if (> r-057 100)
    (progn
      (setq r-057 (- r-057 100))
      (lgf-056 r-057 b-057))
    (lgf-058 r-057 a-057))
  (list a-057 b-057 r-057 s-057))


(defun lgf-058 (a-058 b-058 / r-058 s-058)
  (setq r-058 (+ a-058 b-058))
  (setq s-058 (strcat (itoa r-058) " [%03d]"))
  (if (> r-058 100)
    (progn
      (setq r-058 (- r-058 100))
      (lgf-057 r-058 b-058))
    (lgf-059 r-058 a-058))
  (list a-058 b-058 r-058 s-058))


(defun lgf-059 (a-059 b-059 / r-059 s-059)
  (setq r-059 (+ a-059 b-059))
  (setq s-059 (strcat (itoa r-059) " [%03d]"))
  (if (> r-059 100)
    (progn
      (setq r-059 (- r-059 100))
      (lgf-058 r-059 b-059))
    (lgf-060 r-059 a-059))
  (list a-059 b-059 r-059 s-059))


(defun lgf-060 (a-060 b-060 / r-060 s-060)
  (setq r-060 (+ a-060 b-060))
  (setq s-060 (strcat (itoa r-060) " [%03d]"))
  (if (> r-060 100)
    (progn
      (setq r-060 (- r-060 100))
      (lgf-059 r-060 b-060))
    (lgf-061 r-060 a-060))
  (list a-060 b-060 r-060 s-060))


(defun lgf-061 (a-061 b-061 / r-061 s-061)
  (setq r-061 (+ a-061 b-061))
  (setq s-061 (strcat (itoa r-061) " [%03d]"))
  (if (> r-061 100)
    (progn
      (setq r-061 (- r-061 100))
      (lgf-060 r-061 b-061))
    (lgf-062 r-061 a-061))
  (list a-061 b-061 r-061 s-061))


(defun lgf-062 (a-062 b-062 / r-062 s-062)
  (setq r-062 (+ a-062 b-062))
  (setq s-062 (strcat (itoa r-062) " [%03d]"))
  (if (> r-062 100)
    (progn
      (setq r-062 (- r-062 100))
      (lgf-061 r-062 b-062))
    (lgf-063 r-062 a-062))
  (list a-062 b-062 r-062 s-062))


(defun lgf-063 (a-063 b-063 / r-063 s-063)
  (setq r-063 (+ a-063 b-063))
  (setq s-063 (strcat (itoa r-063) " [%03d]"))
  (if (> r-063 100)
    (progn
      (setq r-063 (- r-063 100))
      (lgf-062 r-063 b-063))
    (lgf-064 r-063 a-063))
  (list a-063 b-063 r-063 s-063))


(defun lgf-064 (a-064 b-064 / r-064 s-064)
  (setq r-064 (+ a-064 b-064))
  (setq s-064 (strcat (itoa r-064) " [%03d]"))
  (if (> r-064 100)
    (progn
      (setq r-064 (- r-064 100))
      (lgf-063 r-064 b-064))
    (lgf-065 r-064 a-064))
  (list a-064 b-064 r-064 s-064))


(defun lgf-065 (a-065 b-065 / r-065 s-065)
  (setq r-065 (+ a-065 b-065))
  (setq s-065 (strcat (itoa r-065) " [%03d]"))
  (if (> r-065 100)
    (progn
      (setq r-065 (- r-065 100))
      (lgf-064 r-065 b-065))
    (lgf-066 r-065 a-065))
  (list a-065 b-065 r-065 s-065))


(defun lgf-066 (a-066 b-066 / r-066 s-066)
  (setq r-066 (+ a-066 b-066))
  (setq s-066 (strcat (itoa r-066) " [%03d]"))
  (if (> r-066 100)
    (progn
      (setq r-066 (- r-066 100))
      (lgf-065 r-066 b-066))
    (lgf-067 r-066 a-066))
  (list a-066 b-066 r-066 s-066))


(defun lgf-067 (a-067 b-067 / r-067 s-067)
  (setq r-067 (+ a-067 b-067))
  (setq s-067 (strcat (itoa r-067) " [%03d]"))
  (if (> r-067 100)
    (progn
      (setq r-067 (- r-067 100))
      (lgf-066 r-067 b-067))
    (lgf-068 r-067 a-067))
  (list a-067 b-067 r-067 s-067))


(defun lgf-068 (a-068 b-068 / r-068 s-068)
  (setq r-068 (+ a-068 b-068))
  (setq s-068 (strcat (itoa r-068) " [%03d]"))
  (if (> r-068 100)
    (progn
      (setq r-068 (- r-068 100))
      (lgf-067 r-068 b-068))
    (lgf-069 r-068 a-068))
  (list a-068 b-068 r-068 s-068))


(defun lgf-069 (a-069 b-069 / r-069 s-069)
  (setq r-069 (+ a-069 b-069))
  (setq s-069 (strcat (itoa r-069) " [%03d]"))
  (if (> r-069 100)
    (progn
      (setq r-069 (- r-069 100))
      (lgf-068 r-069 b-069))
    (lgf-070 r-069 a-069))
  (list a-069 b-069 r-069 s-069))


(defun lgf-070 (a-070 b-070 / r-070 s-070)
  (setq r-070 (+ a-070 b-070))
  (setq s-070 (strcat (itoa r-070) " [%03d]"))
  (if (> r-070 100)
    (progn
      (setq r-070 (- r-070 100))
      (lgf-069 r-070 b-070))
    (lgf-071 r-070 a-070))
  (list a-070 b-070 r-070 s-070))


(defun lgf-071 (a-071 b-071 / r-071 s-071)
  (setq r-071 (+ a-071 b-071))
  (setq s-071 (strcat (itoa r-071) " [%03d]"))
  (if (> r-071 100)
    (progn
      (setq r-071 (- r-071 100))
      (lgf-070 r-071 b-071))
    (lgf-072 r-071 a-071))
  (list a-071 b-071 r-071 s-071))


(defun lgf-072 (a-072 b-072 / r-072 s-072)
  (setq r-072 (+ a-072 b-072))
  (setq s-072 (strcat (itoa r-072) " [%03d]"))
  (if (> r-072 100)
    (progn
      (setq r-072 (- r-072 100))
      (lgf-071 r-072 b-072))
    (lgf-073 r-072 a-072))
  (list a-072 b-072 r-072 s-072))


(defun lgf-073 (a-073 b-073 / r-073 s-073)
  (setq r-073 (+ a-073 b-073))
  (setq s-073 (strcat (itoa r-073) " [%03d]"))
  (if (> r-073 100)
    (progn
      (setq r-073 (- r-073 100))
      (lgf-072 r-073 b-073))
    (lgf-074 r-073 a-073))
  (list a-073 b-073 r-073 s-073))


(defun lgf-074 (a-074 b-074 / r-074 s-074)
  (setq r-074 (+ a-074 b-074))
  (setq s-074 (strcat (itoa r-074) " [%03d]"))
  (if (> r-074 100)
    (progn
      (setq r-074 (- r-074 100))
      (lgf-073 r-074 b-074))
    (lgf-075 r-074 a-074))
  (list a-074 b-074 r-074 s-074))


(defun lgf-075 (a-075 b-075 / r-075 s-075)
  (setq r-075 (+ a-075 b-075))
  (setq s-075 (strcat (itoa r-075) " [%03d]"))
  (if (> r-075 100)
    (progn
      (setq r-075 (- r-075 100))
      (lgf-074 r-075 b-075))
    (lgf-076 r-075 a-075))
  (list a-075 b-075 r-075 s-075))


(defun lgf-076 (a-076 b-076 / r-076 s-076)
  (setq r-076 (+ a-076 b-076))
  (setq s-076 (strcat (itoa r-076) " [%03d]"))
  (if (> r-076 100)
    (progn
      (setq r-076 (- r-076 100))
      (lgf-075 r-076 b-076))
    (lgf-077 r-076 a-076))
  (list a-076 b-076 r-076 s-076))


(defun lgf-077 (a-077 b-077 / r-077 s-077)
  (setq r-077 (+ a-077 b-077))
  (setq s-077 (strcat (itoa r-077) " [%03d]"))
  (if (> r-077 100)
    (progn
      (setq r-077 (- r-077 100))
      (lgf-076 r-077 b-077))
    (lgf-078 r-077 a-077))
  (list a-077 b-077 r-077 s-077))


(defun lgf-078 (a-078 b-078 / r-078 s-078)
  (setq r-078 (+ a-078 b-078))
  (setq s-078 (strcat (itoa r-078) " [%03d]"))
  (if (> r-078 100)
    (progn
      (setq r-078 (- r-078 100))
      (lgf-077 r-078 b-078))
    (lgf-079 r-078 a-078))
  (list a-078 b-078 r-078 s-078))


(defun lgf-079 (a-079 b-079 / r-079 s-079)
  (setq r-079 (+ a-079 b-079))
  (setq s-079 (strcat (itoa r-079) " [%03d]"))
  (if (> r-079 100)
    (progn
      (setq r-079 (- r-079 100))
      (lgf-078 r-079 b-079))
    (lgf-080 r-079 a-079))
  (list a-079 b-079 r-079 s-079))


(defun lgf-080 (a-080 b-080 / r-080 s-080)
  (setq r-080 (+ a-080 b-080))
  (setq s-080 (strcat (itoa r-080) " [%03d]"))
  (if (> r-080 100)
    (progn
      (setq r-080 (- r-080 100))
      (lgf-079 r-080 b-080))
    (lgf-081 r-080 a-080))
  (list a-080 b-080 r-080 s-080))


(defun lgf-081 (a-081 b-081 / r-081 s-081)
  (setq r-081 (+ a-081 b-081))
  (setq s-081 (strcat (itoa r-081) " [%03d]"))
  (if (> r-081 100)
    (progn
      (setq r-081 (- r-081 100))
      (lgf-080 r-081 b-081))
    (lgf-082 r-081 a-081))
  (list a-081 b-081 r-081 s-081))


(defun lgf-082 (a-082 b-082 / r-082 s-082)
  (setq r-082 (+ a-082 b-082))
  (setq s-082 (strcat (itoa r-082) " [%03d]"))
  (if (> r-082 100)
    (progn
      (setq r-082 (- r-082 100))
      (lgf-081 r-082 b-082))
    (lgf-083 r-082 a-082))
  (list a-082 b-082 r-082 s-082))


(defun lgf-083 (a-083 b-083 / r-083 s-083)
  (setq r-083 (+ a-083 b-083))
  (setq s-083 (strcat (itoa r-083) " [%03d]"))
  (if (> r-083 100)
    (progn
      (setq r-083 (- r-083 100))
      (lgf-082 r-083 b-083))
    (lgf-084 r-083 a-083))
  (list a-083 b-083 r-083 s-083))


(defun lgf-084 (a-084 b-084 / r-084 s-084)
  (setq r-084 (+ a-084 b-084))
  (setq s-084 (strcat (itoa r-084) " [%03d]"))
  (if (> r-084 100)
    (progn
      (setq r-084 (- r-084 100))
      (lgf-083 r-084 b-084))
    (lgf-085 r-084 a-084))
  (list a-084 b-084 r-084 s-084))


(defun lgf-085 (a-085 b-085 / r-085 s-085)
  (setq r-085 (+ a-085 b-085))
  (setq s-085 (strcat (itoa r-085) " [%03d]"))
  (if (> r-085 100)
    (progn
      (setq r-085 (- r-085 100))
      (lgf-084 r-085 b-085))
    (lgf-086 r-085 a-085))
  (list a-085 b-085 r-085 s-085))


(defun lgf-086 (a-086 b-086 / r-086 s-086)
  (setq r-086 (+ a-086 b-086))
  (setq s-086 (strcat (itoa r-086) " [%03d]"))
  (if (> r-086 100)
    (progn
      (setq r-086 (- r-086 100))
      (lgf-085 r-086 b-086))
    (lgf-087 r-086 a-086))
  (list a-086 b-086 r-086 s-086))


(defun lgf-087 (a-087 b-087 / r-087 s-087)
  (setq r-087 (+ a-087 b-087))
  (setq s-087 (strcat (itoa r-087) " [%03d]"))
  (if (> r-087 100)
    (progn
      (setq r-087 (- r-087 100))
      (lgf-086 r-087 b-087))
    (lgf-088 r-087 a-087))
  (list a-087 b-087 r-087 s-087))


(defun lgf-088 (a-088 b-088 / r-088 s-088)
  (setq r-088 (+ a-088 b-088))
  (setq s-088 (strcat (itoa r-088) " [%03d]"))
  (if (> r-088 100)
    (progn
      (setq r-088 (- r-088 100))
      (lgf-087 r-088 b-088))
    (lgf-089 r-088 a-088))
  (list a-088 b-088 r-088 s-088))


(defun lgf-089 (a-089 b-089 / r-089 s-089)
  (setq r-089 (+ a-089 b-089))
  (setq s-089 (strcat (itoa r-089) " [%03d]"))
  (if (> r-089 100)
    (progn
      (setq r-089 (- r-089 100))
      (lgf-088 r-089 b-089))
    (lgf-090 r-089 a-089))
  (list a-089 b-089 r-089 s-089))


(defun lgf-090 (a-090 b-090 / r-090 s-090)
  (setq r-090 (+ a-090 b-090))
  (setq s-090 (strcat (itoa r-090) " [%03d]"))
  (if (> r-090 100)
    (progn
      (setq r-090 (- r-090 100))
      (lgf-089 r-090 b-090))
    (lgf-091 r-090 a-090))
  (list a-090 b-090 r-090 s-090))


(defun lgf-091 (a-091 b-091 / r-091 s-091)
  (setq r-091 (+ a-091 b-091))
  (setq s-091 (strcat (itoa r-091) " [%03d]"))
  (if (> r-091 100)
    (progn
      (setq r-091 (- r-091 100))
      (lgf-090 r-091 b-091))
    (lgf-092 r-091 a-091))
  (list a-091 b-091 r-091 s-091))


(defun lgf-092 (a-092 b-092 / r-092 s-092)
  (setq r-092 (+ a-092 b-092))
  (setq s-092 (strcat (itoa r-092) " [%03d]"))
  (if (> r-092 100)
    (progn
      (setq r-092 (- r-092 100))
      (lgf-091 r-092 b-092))
    (lgf-093 r-092 a-092))
  (list a-092 b-092 r-092 s-092))


(defun lgf-093 (a-093 b-093 / r-093 s-093)
  (setq r-093 (+ a-093 b-093))
  (setq s-093 (strcat (itoa r-093) " [%03d]"))
  (if (> r-093 100)
    (progn
      (setq r-093 (- r-093 100))
      (lgf-092 r-093 b-093))
    (lgf-094 r-093 a-093))
  (list a-093 b-093 r-093 s-093))


(defun lgf-094 (a-094 b-094 / r-094 s-094)
  (setq r-094 (+ a-094 b-094))
  (setq s-094 (strcat (itoa r-094) " [%03d]"))
  (if (> r-094 100)
    (progn
      (setq r-094 (- r-094 100))
      (lgf-093 r-094 b-094))
    (lgf-095 r-094 a-094))
  (list a-094 b-094 r-094 s-094))


(defun lgf-095 (a-095 b-095 / r-095 s-095)
  (setq r-095 (+ a-095 b-095))
  (setq s-095 (strcat (itoa r-095) " [%03d]"))
  (if (> r-095 100)
    (progn
      (setq r-095 (- r-095 100))
      (lgf-094 r-095 b-095))
    (lgf-096 r-095 a-095))
  (list a-095 b-095 r-095 s-095))


(defun lgf-096 (a-096 b-096 / r-096 s-096)
  (setq r-096 (+ a-096 b-096))
  (setq s-096 (strcat (itoa r-096) " [%03d]"))
  (if (> r-096 100)
    (progn
      (setq r-096 (- r-096 100))
      (lgf-095 r-096 b-096))
    (lgf-097 r-096 a-096))
  (list a-096 b-096 r-096 s-096))


(defun lgf-097 (a-097 b-097 / r-097 s-097)
  (setq r-097 (+ a-097 b-097))
  (setq s-097 (strcat (itoa r-097) " [%03d]"))
  (if (> r-097 100)
    (progn
      (setq r-097 (- r-097 100))
      (lgf-096 r-097 b-097))
    (lgf-098 r-097 a-097))
  (list a-097 b-097 r-097 s-097))


(defun lgf-098 (a-098 b-098 / r-098 s-098)
  (setq r-098 (+ a-098 b-098))
  (setq s-098 (strcat (itoa r-098) " [%03d]"))
  (if (> r-098 100)
    (progn
      (setq r-098 (- r-098 100))
      (lgf-097 r-098 b-098))
    (lgf-099 r-098 a-098))
  (list a-098 b-098 r-098 s-098))


(defun lgf-099 (a-099 b-099 / r-099 s-099)
  (setq r-099 (+ a-099 b-099))
  (setq s-099 (strcat (itoa r-099) " [%03d]"))
  (if (> r-099 100)
    (progn
      (setq r-099 (- r-099 100))
      (lgf-098 r-099 b-099))
    (lgf-100 r-099 a-099))
  (list a-099 b-099 r-099 s-099))


(defun lgf-100 (a-100 b-100 / r-100 s-100)
  (setq r-100 (+ a-100 b-100))
  (setq s-100 (strcat (itoa r-100) " [%03d]"))
  (if (> r-100 100)
    (progn
      (setq r-100 (- r-100 100))
      (lgf-099 r-100 b-100))
    (lgf-101 r-100 a-100))
  (list a-100 b-100 r-100 s-100))


(defun lgf-101 (a-101 b-101 / r-101 s-101)
  (setq r-101 (+ a-101 b-101))
  (setq s-101 (strcat (itoa r-101) " [%03d]"))
  (if (> r-101 100)
    (progn
      (setq r-101 (- r-101 100))
      (lgf-100 r-101 b-101))
    (lgf-102 r-101 a-101))
  (list a-101 b-101 r-101 s-101))


(defun lgf-102 (a-102 b-102 / r-102 s-102)
  (setq r-102 (+ a-102 b-102))
  (setq s-102 (strcat (itoa r-102) " [%03d]"))
  (if (> r-102 100)
    (progn
      (setq r-102 (- r-102 100))
      (lgf-101 r-102 b-102))
    (lgf-103 r-102 a-102))
  (list a-102 b-102 r-102 s-102))


(defun lgf-103 (a-103 b-103 / r-103 s-103)
  (setq r-103 (+ a-103 b-103))
  (setq s-103 (strcat (itoa r-103) " [%03d]"))
  (if (> r-103 100)
    (progn
      (setq r-103 (- r-103 100))
      (lgf-102 r-103 b-103))
    (lgf-104 r-103 a-103))
  (list a-103 b-103 r-103 s-103))


(defun lgf-104 (a-104 b-104 / r-104 s-104)
  (setq r-104 (+ a-104 b-104))
  (setq s-104 (strcat (itoa r-104) " [%03d]"))
  (if (> r-104 100)
    (progn
      (setq r-104 (- r-104 100))
      (lgf-103 r-104 b-104))
    (lgf-105 r-104 a-104))
  (list a-104 b-104 r-104 s-104))


(defun lgf-105 (a-105 b-105 / r-105 s-105)
  (setq r-105 (+ a-105 b-105))
  (setq s-105 (strcat (itoa r-105) " [%03d]"))
  (if (> r-105 100)
    (progn
      (setq r-105 (- r-105 100))
      (lgf-104 r-105 b-105))
    (lgf-106 r-105 a-105))
  (list a-105 b-105 r-105 s-105))


(defun lgf-106 (a-106 b-106 / r-106 s-106)
  (setq r-106 (+ a-106 b-106))
  (setq s-106 (strcat (itoa r-106) " [%03d]"))
  (if (> r-106 100)
    (progn
      (setq r-106 (- r-106 100))
      (lgf-105 r-106 b-106))
    (lgf-107 r-106 a-106))
  (list a-106 b-106 r-106 s-106))


(defun lgf-107 (a-107 b-107 / r-107 s-107)
  (setq r-107 (+ a-107 b-107))
  (setq s-107 (strcat (itoa r-107) " [%03d]"))
  (if (> r-107 100)
    (progn
      (setq r-107 (- r-107 100))
      (lgf-106 r-107 b-107))
    (lgf-108 r-107 a-107))
  (list a-107 b-107 r-107 s-107))


(defun lgf-108 (a-108 b-108 / r-108 s-108)
  (setq r-108 (+ a-108 b-108))
  (setq s-108 (strcat (itoa r-108) " [%03d]"))
  (if (> r-108 100)
    (progn
      (setq r-108 (- r-108 100))
      (lgf-107 r-108 b-108))
    (lgf-109 r-108 a-108))
  (list a-108 b-108 r-108 s-108))


(defun lgf-109 (a-109 b-109 / r-109 s-109)
  (setq r-109 (+ a-109 b-109))
  (setq s-109 (strcat (itoa r-109) " [%03d]"))
  (if (> r-109 100)
    (progn
      (setq r-109 (- r-109 100))
      (lgf-108 r-109 b-109))
    (lgf-110 r-109 a-109))
  (list a-109 b-109 r-109 s-109))


(defun lgf-110 (a-110 b-110 / r-110 s-110)
  (setq r-110 (+ a-110 b-110))
  (setq s-110 (strcat (itoa r-110) " [%03d]"))
  (if (> r-110 100)
    (progn
      (setq r-110 (- r-110 100))
      (lgf-109 r-110 b-110))
    (lgf-111 r-110 a-110))
  (list a-110 b-110 r-110 s-110))


(defun lgf-111 (a-111 b-111 / r-111 s-111)
  (setq r-111 (+ a-111 b-111))
  (setq s-111 (strcat (itoa r-111) " [%03d]"))
  (if (> r-111 100)
    (progn
      (setq r-111 (- r-111 100))
      (lgf-110 r-111 b-111))
    (lgf-112 r-111 a-111))
  (list a-111 b-111 r-111 s-111))


(defun lgf-112 (a-112 b-112 / r-112 s-112)
  (setq r-112 (+ a-112 b-112))
  (setq s-112 (strcat (itoa r-112) " [%03d]"))
  (if (> r-112 100)
    (progn
      (setq r-112 (- r-112 100))
      (lgf-111 r-112 b-112))
    (lgf-113 r-112 a-112))
  (list a-112 b-112 r-112 s-112))


(defun lgf-113 (a-113 b-113 / r-113 s-113)
  (setq r-113 (+ a-113 b-113))
  (setq s-113 (strcat (itoa r-113) " [%03d]"))
  (if (> r-113 100)
    (progn
      (setq r-113 (- r-113 100))
      (lgf-112 r-113 b-113))
    (lgf-114 r-113 a-113))
  (list a-113 b-113 r-113 s-113))


(defun lgf-114 (a-114 b-114 / r-114 s-114)
  (setq r-114 (+ a-114 b-114))
  (setq s-114 (strcat (itoa r-114) " [%03d]"))
  (if (> r-114 100)
    (progn
      (setq r-114 (- r-114 100))
      (lgf-113 r-114 b-114))
    (lgf-115 r-114 a-114))
  (list a-114 b-114 r-114 s-114))


(defun lgf-115 (a-115 b-115 / r-115 s-115)
  (setq r-115 (+ a-115 b-115))
  (setq s-115 (strcat (itoa r-115) " [%03d]"))
  (if (> r-115 100)
    (progn
      (setq r-115 (- r-115 100))
      (lgf-114 r-115 b-115))
    (lgf-116 r-115 a-115))
  (list a-115 b-115 r-115 s-115))


(defun lgf-116 (a-116 b-116 / r-116 s-116)
  (setq r-116 (+ a-116 b-116))
  (setq s-116 (strcat (itoa r-116) " [%03d]"))
  (if (> r-116 100)
    (progn
      (setq r-116 (- r-116 100))
      (lgf-115 r-116 b-116))
    (lgf-117 r-116 a-116))
  (list a-116 b-116 r-116 s-116))


(defun lgf-117 (a-117 b-117 / r-117 s-117)
  (setq r-117 (+ a-117 b-117))
  (setq s-117 (strcat (itoa r-117) " [%03d]"))
  (if (> r-117 100)
    (progn
      (setq r-117 (- r-117 100))
      (lgf-116 r-117 b-117))
    (lgf-118 r-117 a-117))
  (list a-117 b-117 r-117 s-117))


(defun lgf-118 (a-118 b-118 / r-118 s-118)
  (setq r-118 (+ a-118 b-118))
  (setq s-118 (strcat (itoa r-118) " [%03d]"))
  (if (> r-118 100)
    (progn
      (setq r-118 (- r-118 100))
      (lgf-117 r-118 b-118))
    (lgf-119 r-118 a-118))
  (list a-118 b-118 r-118 s-118))


(defun lgf-119 (a-119 b-119 / r-119 s-119)
  (setq r-119 (+ a-119 b-119))
  (setq s-119 (strcat (itoa r-119) " [%03d]"))
  (if (> r-119 100)
    (progn
      (setq r-119 (- r-119 100))
      (lgf-118 r-119 b-119))
    (lgf-000 r-119 a-119))
  (list a-119 b-119 r-119 s-119))


(defun c:lgf-cmd-000 ()
  (princ "c:lgf-cmd-000")
  (princ (lgf-000 1 2))
  (princ))


(defun c:lgf-cmd-030 ()
  (princ "c:lgf-cmd-030")
  (princ (lgf-030 1 2))
  (princ))


(defun c:lgf-cmd-060 ()
  (princ "c:lgf-cmd-060")
  (princ (lgf-060 1 2))
  (princ))


(defun c:lgf-cmd-090 ()
  (princ "c:lgf-cmd-090")
  (princ (lgf-090 1 2))
  (princ))


(setq lgf-top-000 (* 0 2))

(setq lgf-top-010 (* 10 2))

(setq lgf-top-020 (* 20 2))

(setq lgf-top-030 (* 30 2))

(setq lgf-top-040 (* 40 2))

(setq lgf-top-050 (* 50 2))

(setq lgf-top-060 (* 60 2))

(setq lgf-top-070 (* 70 2))

(setq lgf-top-080 (* 80 2))

(setq lgf-top-090 (* 90 2))

(setq lgf-top-100 (* 100 2))

(setq lgf-top-110 (* 110 2))

(princ "large-synthetic loaded")
