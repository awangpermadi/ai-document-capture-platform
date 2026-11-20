import type {
  DocumentActionResponse,
  DocumentApprovalRequest,
  DocumentDeleteResponse,
  DocumentDetail,
  DocumentListItem,
  DocumentListParams,
  DocumentProcessResponse,
} from '../types/document'
import type { ReceiptCorrectionRequest } from '../types/receipt'
import { apiClient } from './client'

export async function getDocuments(
  filters: DocumentListParams = {},
  signal?: AbortSignal,
): Promise<DocumentListItem[]> {
  const query: DocumentListParams = {}
  if (filters.status !== undefined) query.status = filters.status
  if (filters.requires_review !== undefined) {
    query.requires_review = filters.requires_review
  }
  if (filters.limit !== undefined) query.limit = filters.limit
  if (filters.offset !== undefined) query.offset = filters.offset

  const response = await apiClient.get<DocumentListItem[]>('/documents', {
    params: query,
    signal,
  })
  return response.data
}

export async function getDocument(
  documentId: string,
  signal?: AbortSignal,
): Promise<DocumentDetail> {
  const response = await apiClient.get<DocumentDetail>(
    `/documents/${encodeURIComponent(documentId)}`,
    { signal },
  )
  return response.data
}

export async function deleteDocument(
  documentId: string,
): Promise<DocumentDeleteResponse> {
  const response = await apiClient.delete<DocumentDeleteResponse>(
    `/documents/${encodeURIComponent(documentId)}`,
  )
  return response.data
}

export async function processDocument(
  file: File,
): Promise<DocumentProcessResponse> {
  const body = new FormData()
  body.append('file', file)

  const response = await apiClient.post<DocumentProcessResponse>(
    '/documents/process',
    body,
    { timeout: 120_000 },
  )
  return response.data
}

const defaultReviewer = import.meta.env.VITE_DEFAULT_REVIEWER?.trim() || 'developer'

export async function updateReceipt(
  documentId: string,
  correction: ReceiptCorrectionRequest,
  reviewedBy = defaultReviewer,
): Promise<DocumentDetail> {
  const response = await apiClient.put<DocumentDetail>(
    `/documents/${encodeURIComponent(documentId)}/receipt`,
    correction,
    {
      headers: {
        'Content-Type': 'application/json',
        'X-Reviewed-By': reviewedBy,
      },
    },
  )
  return response.data
}

export async function approveDocument(
  documentId: string,
  request: Omit<DocumentApprovalRequest, 'reviewed_by'>,
  reviewedBy = defaultReviewer,
): Promise<DocumentActionResponse> {
  const response = await apiClient.post<DocumentActionResponse>(
    `/documents/${encodeURIComponent(documentId)}/approve`,
    { ...request, reviewed_by: reviewedBy },
    {
      headers: {
        'Content-Type': 'application/json',
      },
    },
  )
  return response.data
}
