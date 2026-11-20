import type { Receipt } from '../../types/receipt'
import { formatCurrency } from '../../utils/currency'
import { formatDate } from '../../utils/date'

interface ReceiptSummaryProps {
  receipt: Receipt
}

export function ReceiptSummary({ receipt }: ReceiptSummaryProps) {
  const { merchant, transaction } = receipt

  return (
    <>
      <section aria-labelledby="merchant-title" className="mobile-card">
        <div className="section-title">
          <h2 id="merchant-title">Merchant</h2>
        </div>
        <dl className="merchant-details">
          <div>
            <dt>Name</dt>
            <dd>{merchant.name || 'Not provided'}</dd>
          </div>
          <div>
            <dt>Address</dt>
            <dd>{merchant.address || 'Not provided'}</dd>
          </div>
          <div>
            <dt>Phone</dt>
            <dd>{merchant.phone || 'Not provided'}</dd>
          </div>
        </dl>
      </section>

      <section aria-labelledby="transaction-title" className="mobile-card">
        <div className="section-title">
          <h2 id="transaction-title">Transaction</h2>
        </div>
        <dl className="receipt-amounts">
          <div><dt>Date</dt><dd>{formatDate(transaction.date)}</dd></div>
          <div>
            <dt>Time</dt>
            <dd>{transaction.time?.slice(0, 5) || '—'}</dd>
          </div>
          <div><dt>Subtotal</dt><dd>{formatCurrency(transaction.subtotal, transaction.currency)}</dd></div>
          <div><dt>Discount</dt><dd>{formatCurrency(transaction.discount, transaction.currency)}</dd></div>
          <div><dt>Tax</dt><dd>{formatCurrency(transaction.tax, transaction.currency)}</dd></div>
          {transaction.tip !== null ? (
            <div><dt>Tip</dt><dd>{formatCurrency(transaction.tip, transaction.currency)}</dd></div>
          ) : null}
          <div className="receipt-amounts__total">
            <dt>Total</dt>
            <dd>{formatCurrency(transaction.total, transaction.currency)}</dd>
          </div>
          <div><dt>Cash</dt><dd>{formatCurrency(transaction.cash, transaction.currency)}</dd></div>
          <div><dt>Change</dt><dd>{formatCurrency(transaction.change, transaction.currency)}</dd></div>
        </dl>
      </section>
    </>
  )
}
