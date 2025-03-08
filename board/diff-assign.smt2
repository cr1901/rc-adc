(set-logic QF_LIA)

(declare-const io!1 Bool)
(declare-const io!2 Bool)
(declare-const io!3 Bool)
(declare-const io!4 Bool)
(declare-const io!7 Bool)
(declare-const io!8 Bool)
(declare-const io!9 Bool)
(declare-const io!10 Bool)

(define-fun used ((p Bool) (n Bool)) Int
    (ite (and p (not n)) 1 0))

(define-fun used!1 () Int (used io!1 io!7))
(define-fun used!2 () Int (used io!3 io!10))
(define-fun used!3 () Int (used io!8 io!4))

(define-fun used!4 () Int (used io!1 io!8))
(define-fun used!5 () Int (used io!7 io!2))
(define-fun used!6 () Int (used io!9 io!4))

(define-fun used!7 () Int (used io!7 io!1))
(define-fun used!8 () Int (used io!8 io!2))

(define-fun used-total () Int (+ used!1 used!2 used!3 used!4 used!5 used!6 used!7 used!8))
(define-fun used_port!1 () Bool (>= (+ used!1 used!2 used!3) 1))
(define-fun used_port!2 () Bool (>= (+ used!4 used!5 used!6) 1))
(define-fun used_port!3 () Bool (>= (+ used!7 used!8) 1))

(define-fun io-used!1 () Int (ite (> (+ used!1 used!4 used!7) 0) 1 0))
(define-fun io-used!2 () Int (ite (> (+ used!5 used!8) 0) 1 0))
(define-fun io-used!3 () Int (ite (> (+ used!2) 0) 1 0))
(define-fun io-used!4 () Int (ite (> (+ used!3 used!6) 0) 1 0))
(define-fun io-used!7 () Int (ite (> (+ used!1 used!5 used!7) 0) 1 0))
(define-fun io-used!8 () Int (ite (> (+ used!3 used!4 used!8) 0) 1 0))
(define-fun io-used!9 () Int (ite (> (+ used!6) 0) 1 0))
(define-fun io-used!10 () Int (ite (> (+ used!2) 0) 1 0))

; 0- Negative, 1- Positive, 2- Unused
(define-fun io-type!1 () Int (ite (distinct io-used!1 0) (ite io!1 1 0) 2))
(define-fun io-type!2 () Int (ite (distinct io-used!2 0) (ite io!2 1 0) 2))
(define-fun io-type!3 () Int (ite (distinct io-used!3 0) (ite io!3 1 0) 2))
(define-fun io-type!4 () Int (ite (distinct io-used!4 0) (ite io!4 1 0) 2))
(define-fun io-type!7 () Int (ite (distinct io-used!7 0) (ite io!7 1 0) 2))
(define-fun io-type!8 () Int (ite (distinct io-used!8 0) (ite io!8 1 0) 2))
(define-fun io-type!9 () Int (ite (distinct io-used!9 0) (ite io!9 1 0) 2))
(define-fun io-type!10 () Int (ite (distinct io-used!10 0) (ite io!10 1 0) 2))

; Inherently contradictory.
(assert (distinct used!7 used!1))

(assert (>= used-total 5))
; Use at least one pair from each PMOD
(assert (and used_port!1 used_port!2 used_port!3))
; Tell me which sense line to connect to the PMOD, if any.
(assert (<= (+ io-used!1 io-used!2 io-used!3 io-used!4 io-used!7 io-used!8 io-used!9 io-used!10) 6))

(check-sat)
; (get-model)
(get-value (used!1 used!2 used!3 used!4 used!5 used!6 used!7 used!8))
; (get-value (io!1 io!2 io!3 io!4 io!7 io!8 io!9 io!10))
; (get-value (io-used!1 io-used!2 io-used!3 io-used!4 io-used!7 io-used!8 io-used!9 io-used!10))
(get-value (io-type!1 io-type!2 io-type!3 io-type!4 io-type!7 io-type!8 io-type!9 io-type!10))
