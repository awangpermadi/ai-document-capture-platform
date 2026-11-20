import {
  ArrowLeft,
  ArrowRight,
  Check,
  FileStack,
  FileText,
  Trash2,
  TriangleAlert,
} from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import {
  normalizeApiError,
  normalizeDocumentDeleteError,
} from '../api/client'
import { deleteDocument, getDocuments } from '../api/documents'
import { DeleteDocumentDialog } from '../components/common/DeleteDocumentDialog'
import { EmptyState } from '../components/common/EmptyState'
import { ErrorState } from '../components/common/ErrorState'
import { LoadingState } from '../components/common/LoadingState'
import { StatusBadge } from '../components/common/StatusBadge'
import {
  DocumentStatus,
  type DocumentListItem,
  type DocumentListParams,
} from '../types/document'
import { formatDateTime } from '../utils/date'

type StatusFilter = 'all' | DocumentStatus
type ReviewFilter = 'all' | 'yes' | 'no'

interface QueueState {
  key: string
  documents?: DocumentListItem[]
  error?: string
}

function hasDeletionNotice(state: unknown): boolean {
  return typeof state === 'object'
    && state !== null
    && 'documentDeleted' in state
    && state.documentDeleted === true
}

function getDeletionWarning(state: unknown): string | null {
  if (
    typeof state !== 'object'
    || state === null
    || !('documentDeleted' in state)
    || state.documentDeleted !== true
    || !('deletionWarning' in state)
    || typeof state.deletionWarning !== 'string'
  ) {
    return null
  }
  return state.deletionWarning
}

const PAGE_SIZE_OPTIONS = [25, 50, 100] as const
const DEFAULT_PAGE_SIZE = 50

const statusOptions: Array<{ value: DocumentStatus; label: string }> = [
  { value: DocumentStatus.UPLOADED, label: 'UPLOADED' },
  { value: DocumentStatus.PROCESSING, label: 'PROCESSING' },
  { value: DocumentStatus.EXTRACTED, label: 'EXTRACTED' },
  { value: DocumentStatus.REVIEW_REQUIRED, label: 'REVIEW_REQUIRED' },
  { value: DocumentStatus.APPROVED, label: 'APPROVED' },
  { value: DocumentStatus.FAILED, label: 'FAILED' },
]

export function DocumentsPage() {
  const location = useLocation()
  const navigate = useNavigate()
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')
  const [reviewFilter, setReviewFilter] = useState<ReviewFilter>('all')
  const [pageSize, setPageSize] = useState<number>(DEFAULT_PAGE_SIZE)
  const [pageIndex, setPageIndex] = useState(0)
  const [retry, setRetry] = useState(0)
  const [state, setState] = useState<QueueState | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<DocumentListItem | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const [successMessage, setSuccessMessage] = useState<string | null>(() =>
    hasDeletionNotice(location.state) ? 'Document deleted' : null)
  const [successWarning, setSuccessWarning] = useState<string | null>(() =>
    getDeletionWarning(location.state))
  const [successSequence, setSuccessSequence] = useState(0)
  const successNoticeRef = useRef<HTMLDivElement>(null)
  const stateKey = `${statusFilter}:${reviewFilter}:${pageSize}:${pageIndex}:${retry}`

  useEffect(() => {
    const controller = new AbortController()
    const filters: DocumentListParams = { limit: pageSize }

    if (statusFilter !== 'all') filters.status = statusFilter
    if (reviewFilter !== 'all') {
      filters.requires_review = reviewFilter === 'yes'
    }
    if (pageIndex > 0) filters.offset = pageIndex * pageSize

    void getDocuments(filters, controller.signal)
      .then((documents) => setState({ key: stateKey, documents }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        setState({
          key: stateKey,
          error: normalizeApiError(error).message,
        })
      })

    return () => controller.abort()
  }, [pageIndex, pageSize, retry, reviewFilter, stateKey, statusFilter])

  useEffect(() => {
    if (!hasDeletionNotice(location.state)) return
    navigate(location.pathname, { replace: true, state: null })
  }, [location.key, location.pathname, location.state, navigate])

  useEffect(() => {
    if (successMessage) successNoticeRef.current?.focus()
  }, [successMessage, successSequence])

  const loading = state?.key !== stateKey
  const documents = state?.key === stateKey ? state.documents : undefined
  const error = state?.key === stateKey ? state.error : undefined

  function requestDelete(document: DocumentListItem) {
    if (document.status === DocumentStatus.APPROVED || deleting) return
    setDeleteError(null)
    setDeleteTarget(document)
  }

  function cancelDelete() {
    if (deleting) return
    setDeleteError(null)
    setDeleteTarget(null)
  }

  async function confirmDelete() {
    if (
      !deleteTarget
      || deleting
      || deleteTarget.status === DocumentStatus.APPROVED
    ) {
      return
    }

    setDeleting(true)
    setDeleteError(null)
    try {
      const response = await deleteDocument(deleteTarget.id)
      setState((current) => current?.documents
        ? {
            ...current,
            documents: current.documents.filter(
              (document) => document.id !== deleteTarget.id,
            ),
          }
        : current)
      if (pageIndex > 0 && documents?.length === 1) {
        setPageIndex((current) => Math.max(0, current - 1))
      }
      setDeleteTarget(null)
      setSuccessMessage('Document deleted')
      setSuccessWarning(response.warning ?? null)
      setSuccessSequence((current) => current + 1)
    } catch (deleteError: unknown) {
      setDeleteError(normalizeDocumentDeleteError(deleteError).message)
    } finally {
      setDeleting(false)
    }
  }

  function changeStatus(value: string) {
    setStatusFilter(value === 'all' ? 'all' : value as DocumentStatus)
    setPageIndex(0)
  }

  function changeReview(value: string) {
    setReviewFilter(value as ReviewFilter)
    setPageIndex(0)
  }

  function changePageSize(value: string) {
    setPageSize(Number(value))
    setPageIndex(0)
  }

  return (
    <div className="page document-queue-page">
      <section className="page-intro">
        <div>
          <p className="eyebrow">DOCUMENT MANAGEMENT</p>
          <h2>Documents</h2>
          <p>Review and manage processed documents.</p>
        </div>
        <div className="queue-filters">
          <label className="filter-field">
            <span>Status</span>
            <select
              onChange={(event) => changeStatus(event.target.value)}
              value={statusFilter}
            >
              <option value="all">All</option>
              {statusOptions.map(({ value, label }) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
          </label>
          <label className="filter-field">
            <span>Requires Review</span>
            <select
              onChange={(event) => changeReview(event.target.value)}
              value={reviewFilter}
            >
              <option value="all">All</option>
              <option value="yes">Yes</option>
              <option value="no">No</option>
            </select>
          </label>
          <label className="filter-field filter-field--limit">
            <span>Rows</span>
            <select
              onChange={(event) => changePageSize(event.target.value)}
              value={pageSize}
            >
              {PAGE_SIZE_OPTIONS.map((size) => (
                <option key={size} value={size}>{size}</option>
              ))}
            </select>
          </label>
        </div>
      </section>

      {successMessage ? (
        <div
          className="inline-notice inline-notice--success queue-delete-success"
          ref={successNoticeRef}
          role="status"
          tabIndex={-1}
        >
          <Check aria-hidden="true" size={17} />
          <span>{successMessage}</span>
        </div>
      ) : null}
      {successWarning ? (
        <div className="inline-notice inline-notice--warning queue-delete-warning" role="status">
          <TriangleAlert aria-hidden="true" size={17} />
          <span>{successWarning}</span>
        </div>
      ) : null}

      <section aria-label="Documents" className="content-card">
        {loading ? <LoadingState label="Loading documents…" /> : null}
        {!loading && error ? (
          <ErrorState
            message={error}
            onRetry={() => setRetry((current) => current + 1)}
          />
        ) : null}
        {!loading && !error && documents?.length === 0 ? (
          <EmptyState
            message={
              statusFilter === 'all' && reviewFilter === 'all'
                ? 'Documents will appear here after they are processed.'
                : 'No documents match the selected filters.'
            }
            title="No documents found"
          />
        ) : null}
        {!loading && !error && documents && documents.length > 0 ? (
          <>
            <div className="content-card__heading content-card__heading--queue">
              <div>
                <h2>Document queue</h2>
                <p>{documents.length} {documents.length === 1 ? 'document' : 'documents'} on this page</p>
              </div>
              <FileStack aria-hidden="true" size={20} />
            </div>
            <div className="queue-mobile-list">
              {documents.map((document) => (
                <article className="queue-document-card" key={document.id}>
                  <div className="queue-document-card__heading">
                    <div className="queue-document-card__filename">
                      <FileText aria-hidden="true" size={17} />
                      <strong title={document.original_filename}>
                        {document.original_filename}
                      </strong>
                    </div>
                    <StatusBadge status={document.status} />
                  </div>
                  <dl className="queue-document-card__details">
                    <div>
                      <dt>Type</dt>
                      <dd>{document.document_type}</dd>
                    </div>
                    <div>
                      <dt>Extraction</dt>
                      <dd>{document.extraction_method ?? '—'}</dd>
                    </div>
                    <div>
                      <dt>Review</dt>
                      <dd>
                        {document.requires_review
                          ? 'Review Required'
                          : 'No Review Required'}
                      </dd>
                    </div>
                    <div>
                      <dt>Created</dt>
                      <dd>{formatDateTime(document.created_at)}</dd>
                    </div>
                  </dl>
                  <div className="queue-document-card__actions">
                    <Link
                      className="table-action"
                      to={`/documents/${encodeURIComponent(document.id)}`}
                    >
                      View <ArrowRight aria-hidden="true" size={15} />
                    </Link>
                    {document.status !== DocumentStatus.APPROVED ? (
                      <button
                        aria-label={`Delete ${document.original_filename}`}
                        className="document-delete-action"
                        disabled={deleting}
                        onClick={() => requestDelete(document)}
                        type="button"
                      >
                        <Trash2 aria-hidden="true" size={16} />
                        Delete
                      </button>
                    ) : null}
                  </div>
                </article>
              ))}
            </div>
            <div className="table-scroll">
              <table className="data-table">
                <thead>
                  <tr>
                    <th scope="col">Document</th>
                    <th scope="col">Type</th>
                    <th scope="col">Status</th>
                    <th scope="col">Extraction</th>
                    <th scope="col">Review</th>
                    <th scope="col">Created</th>
                    <th scope="col">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {documents.map((document) => (
                    <tr key={document.id}>
                      <td>
                        <span className="document-name-cell">
                          <FileText aria-hidden="true" size={17} />
                          <span
                            className="data-table__filename"
                            title={document.original_filename}
                          >
                            {document.original_filename}
                          </span>
                        </span>
                      </td>
                      <td>{document.document_type}</td>
                      <td><StatusBadge status={document.status} /></td>
                      <td>{document.extraction_method ?? '—'}</td>
                      <td>
                        {document.requires_review
                          ? 'Review Required'
                          : 'No Review Required'}
                      </td>
                      <td>{formatDateTime(document.created_at)}</td>
                      <td>
                        <div className="document-row-actions">
                          <Link
                            className="table-action"
                            to={`/documents/${encodeURIComponent(document.id)}`}
                          >
                            View <ArrowRight aria-hidden="true" size={15} />
                          </Link>
                          {document.status !== DocumentStatus.APPROVED ? (
                            <button
                              aria-label={`Delete ${document.original_filename}`}
                              className="document-delete-action"
                              disabled={deleting}
                              onClick={() => requestDelete(document)}
                              type="button"
                            >
                              <Trash2 aria-hidden="true" size={16} />
                              Delete
                            </button>
                          ) : null}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        ) : null}
        {!loading && !error && documents
        && (documents.length > 0 || pageIndex > 0) ? (
          <nav aria-label="Document pages" className="queue-pagination">
            <span>Page {pageIndex + 1}</span>
            <div>
              <button
                className="button button--secondary"
                disabled={pageIndex === 0}
                onClick={() => setPageIndex((current) => Math.max(0, current - 1))}
                type="button"
              >
                <ArrowLeft aria-hidden="true" size={15} />
                Previous
              </button>
              <button
                className="button button--secondary"
                disabled={documents.length < pageSize}
                onClick={() => setPageIndex((current) => current + 1)}
                type="button"
              >
                Next
                <ArrowRight aria-hidden="true" size={15} />
              </button>
            </div>
          </nav>
        ) : null}
      </section>
      <DeleteDocumentDialog
        deleting={deleting}
        documentName={deleteTarget?.original_filename ?? ''}
        errorMessage={deleteError}
        onCancel={cancelDelete}
        onConfirm={() => void confirmDelete()}
        open={deleteTarget !== null}
      />
    </div>
  )
}
