export interface Merchant {
  name: string | null
  address: string | null
  phone: string | null
}

export interface Transaction {
  date: string | null
  time: string | null
  subtotal: number | null
  discount: number | null
  tax: number | null
  tip: number | null
  total: number | null
  cash: number | null
  change: number | null
  currency: string | null
}

export interface ReceiptItem {
  id: string | null
  description_raw: string | null
  description_normalized: string | null
  quantity: number | null
  unit_price: number | null
  total_price: number | null
  confidence: number | null
  source: string
}

export interface Receipt {
  document_type: string
  merchant: Merchant
  transaction: Transaction
  items: ReceiptItem[]
  extraction_method: string
  confidence: number | null
  requires_review: boolean
  review_reasons: string[]
}

export interface ReceiptItemCorrection {
  id?: string | null
  description_raw: string | null
  description_normalized: string | null
  quantity: number | null
  unit_price: number | null
  total_price: number | null
  confidence?: number | null
  source?: string | null
}

export interface ReceiptCorrectionRequest {
  merchant: Merchant
  transaction: {
    date: string | null
    time: string | null
    subtotal: number | null
    discount: number | null
    tax: number | null
    tip: number | null
    total: number | null
    cash: number | null
    change: number | null
    currency?: string
  }
  items: ReceiptItemCorrection[]
}
