import { ChevronDown, PackageOpen } from 'lucide-react'
import type { ReceiptItem, Transaction } from '../../types/receipt'
import { formatCurrency } from '../../utils/currency'

interface ReceiptItemsProps {
  items: ReceiptItem[]
  transaction: Transaction
}

export function ReceiptItems({ items, transaction }: ReceiptItemsProps) {
  return (
    <section aria-labelledby="receipt-items-title" className="mobile-card">
      <div className="section-title section-title--count">
        <h2 id="receipt-items-title">Items</h2>
        <span>{items.length}</span>
      </div>
      {items.length === 0 ? (
        <div className="receipt-items-empty">
          <PackageOpen aria-hidden="true" size={21} />
          <span>No line items were returned for this receipt.</span>
        </div>
      ) : (
        <div className="receipt-items-list">
          {items.map((item, index) => (
            <details
              className="receipt-item"
              key={item.id ?? `${item.description_raw ?? 'item'}-${index}`}
            >
              <summary>
                <span className="receipt-item__summary">
                  <strong>
                    {item.description_normalized
                      || item.description_raw
                      || 'Unlabeled item'}
                  </strong>
                  <span>
                    {item.quantity ?? '—'} × {formatCurrency(item.unit_price, transaction.currency)}
                  </span>
                </span>
                <span className="receipt-item__summary-end">
                  <strong className="receipt-item__total">
                    {formatCurrency(item.total_price, transaction.currency)}
                  </strong>
                  <ChevronDown aria-hidden="true" size={17} />
                </span>
              </summary>
              <div className="receipt-item__expanded">
                {item.description_normalized && item.description_raw
                && item.description_normalized !== item.description_raw ? (
                  <p className="receipt-item__raw">{item.description_raw}</p>
                ) : null}
                <dl className="receipt-item__details">
                  <div><dt>Quantity</dt><dd>{item.quantity ?? '—'}</dd></div>
                  <div>
                    <dt>Unit price</dt>
                    <dd>{formatCurrency(item.unit_price, transaction.currency)}</dd>
                  </div>
                  <div>
                    <dt>Total</dt>
                    <dd>{formatCurrency(item.total_price, transaction.currency)}</dd>
                  </div>
                </dl>
                {(item.confidence !== null || item.source) ? (
                  <div className="receipt-item__metadata">
                    {item.confidence !== null ? (
                      <span>{Math.round(item.confidence * 100)}% confidence</span>
                    ) : null}
                    {item.source ? <span>{item.source.replaceAll('_', ' ')}</span> : null}
                  </div>
                ) : null}
              </div>
            </details>
          ))}
        </div>
      )}
    </section>
  )
}
