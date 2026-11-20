import type { Receipt, ReceiptCorrectionRequest } from './receipt'

export const DocumentStatus = {
  UPLOADED: 'uploaded',
  PROCESSING: 'processing',
  EXTRACTED: 'extracted',
  REVIEW_REQUIRED: 'review_required',
  APPROVED: 'approved',
  FAILED: 'failed',
} as const

export type DocumentStatus =
  (typeof DocumentStatus)[keyof typeof DocumentStatus]

export interface DocumentListItem {
  id: string
  original_filename: string
  content_type: string
  document_type: string
  status: DocumentStatus
  extraction_method: string | null
  requires_review: boolean
  created_at: string
  updated_at: string
  reviewed_at: string | null
  approved_at: string | null
}

export interface DocumentDetail extends DocumentListItem {
  stored_filename: string | null
  review_reasons: string[]
  error_message: string | null
  receipt: Receipt
  reviewed_by: string | null
}

export interface DocumentProcessResponse {
  document_id: string
  status: string
  receipt: Receipt
  requires_review: boolean
  review_reasons: string[]
  created_at: string
}

export interface DocumentActionResponse {
  document_id: string
  status: string
  message: string
  updated_at: string
  reviewed_at: string | null
  approved_at: string | null
}

export interface DocumentDeleteResponse {
  document_id: string
  status: 'DELETED'
  message: string
  warning?: string | null
}

export interface DocumentApprovalRequest {
  reviewed_by: string
  confirmation: true
}

export interface DocumentListParams {
  status?: DocumentStatus
  requires_review?: boolean
  limit?: number
  offset?: number
}

export type { ReceiptCorrectionRequest }
