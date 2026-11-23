/** Evidence coverage of an expense line, as SQL fragments (shared by api.ts, asamblea.ts).
 *  Mirrors `line_coverage` in pipeline/alas3/review.py and the ask_gastos view. */

/** A link counts as "has a receipt" when a human confirmed it or the match is confident;
 *  "posible coincidencia" links (score < 0.9) are shown but not counted as coverage. */
export const COVERED = "(l.status = 'verified' OR (l.status = 'auto' AND l.score >= 0.9))";
/** A receipt, or the month's grouped bank charges: for those the statement itself is the voucher. */
export const HAS_RECEIPT = (e: string) =>
  `(EXISTS (SELECT 1 FROM expense_ticket_links l WHERE l.expense_line_id = ${e}.id AND ${COVERED})
    OR EXISTS (SELECT 1 FROM expense_payment_links l JOIN bank_movements b ON b.id = l.movement_id
               WHERE l.expense_line_id = ${e}.id AND b.kind = 'gastos' AND ${COVERED}))`;
export const HAS_PAYMENT = (e: string) =>
  `EXISTS (SELECT 1 FROM expense_payment_links l WHERE l.expense_line_id = ${e}.id AND ${COVERED})`;
/** Months whose receipts bundle was uploaded (a receipt's own month can be older: an old
 *  invoice billed in a later liquidación does not make its month "have receipts"). */
export const RECEIPT_PERIODS =
  "SELECT d.period AS period_id FROM tickets t JOIN documents d ON d.id = t.document_id WHERE d.period IS NOT NULL";
/** Months with a bank statement (a cheque not cleared yet is not one). */
export const PAYMENT_PERIODS = "SELECT period_id FROM bank_movements WHERE kind != 'cheque'";
/** Receipts of the line's month or the one before exist (matching pairs a line with both, match.py). */
export const RECEIPTS_FOR = (e: string) =>
  `(${e}.period_id IN (${RECEIPT_PERIODS}) OR strftime('%Y-%m', ${e}.period_id || '-01', '-1 month') IN (${RECEIPT_PERIODS}))`;
/** The bank statement of the line's own month was uploaded. */
export const STATEMENT_FOR = (e: string) => `${e}.period_id IN (${PAYMENT_PERIODS})`;
/** A receipt (what was bought) is missing: there are receipts for that month but none is linked. */
export const LACKS_RECEIPT = (e: string) => `(NOT ${HAS_RECEIPT(e)} AND ${RECEIPTS_FOR(e)})`;
/** A bank payment (that it was paid) is missing: there is a bank statement for its month but no linked debit. */
export const LACKS_PAYMENT = (e: string) => `(NOT ${HAS_PAYMENT(e)} AND ${STATEMENT_FOR(e)})`;
/** A line is backed when it has a receipt AND a bank payment, each one required only when that
 *  kind of evidence was uploaded for its month; and at least one of them. `e` = expense_lines alias. */
export const BACKED = (e: string) =>
  `((${HAS_RECEIPT(e)} OR ${HAS_PAYMENT(e)}) AND NOT ${LACKS_RECEIPT(e)} AND NOT ${LACKS_PAYMENT(e)})`;
/** Periods with uploaded evidence (receipts or a bank statement): only there "sin comprobante" means something. */
export const EVIDENCE_PERIODS = `${RECEIPT_PERIODS} UNION ${PAYMENT_PERIODS}`;
