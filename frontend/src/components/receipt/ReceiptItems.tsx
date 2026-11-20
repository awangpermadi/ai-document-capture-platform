import { PackageOpen } from 'lucide-react'
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
        <h2 id="receipt-items-title">Receipt items</h2>
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
            <article
              className="receipt-item"
              key={item.id ?? `${item.description_raw ?? 'item'}-${index}`}
            >
              <div className="receipt-item__top">
                <strong>
                  {item.description_normalized
                    || item.description_raw
                    || 'Unlabeled item'}
                </strong>
                <span className="receipt-item__total">
                  {formatCurrency(item.total_price, transaction.currency)}
                </span>
              </div>
              {item.description_normalized && item.description_raw
              && item.description_normalized !== item.description_raw ? (
                <span className="receipt-item__raw">{item.description_raw}</span>
              ) : null}
              <div className="receipt-item__details">
                <span>Qty {item.quantity ?? '—'}</span>
                <span>{formatCurrency(item.unit_price, transaction.currency)} each</span>
              </div>
              {(item.confidence !== null || item.source) ? (
                <div className="receipt-item__metadata">
                  {item.confidence !== null ? (
                    <span>Confidence {Math.round(item.confidence * 100)}%</span>
                  ) : null}
                  {item.source ? <span>{item.source.replaceAll('_', ' ')}</span> : null}
                </div>
              ) : null}
            </article>
          ))}
        </div>
      )}
    </section>
  )
}
