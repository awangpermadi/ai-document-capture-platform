import { CalendarDays, MapPin, Phone } from 'lucide-react'
import type { Receipt } from '../../types/receipt'
import { formatCurrency } from '../../utils/currency'
import { formatDate } from '../../utils/date'

interface ReceiptSummaryProps {
  receipt: Receipt
}

export function ReceiptSummary({ receipt }: ReceiptSummaryProps) {
  const { merchant, transaction } = receipt

  return (
    <section aria-labelledby="receipt-summary-title" className="mobile-card">
      <div className="section-title">
        <h2 id="receipt-summary-title">Receipt summary</h2>
      </div>
      <div className="merchant-block">
        <strong>{merchant.name || 'Merchant not identified'}</strong>
        {merchant.address ? (
          <span><MapPin aria-hidden="true" size={15} />{merchant.address}</span>
        ) : null}
        {merchant.phone ? (
          <span><Phone aria-hidden="true" size={15} />{merchant.phone}</span>
        ) : null}
      </div>
      <dl className="receipt-amounts">
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
      <p className="receipt-date">
        <CalendarDays aria-hidden="true" size={15} />
        {formatDate(transaction.date)}
        {transaction.time ? ` · ${transaction.time.slice(0, 5)}` : ''}
      </p>
    </section>
  )
}
