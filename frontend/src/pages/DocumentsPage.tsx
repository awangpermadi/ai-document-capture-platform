import {
  Camera,
  ChevronRight,
  EllipsisVertical,
  FileImage,
  FileText,
  Trash2,
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
import { StatusBadge } from '../components/common/StatusBadge'
import { Toast } from '../components/common/Toast'
import {
  DocumentStatus,
  type DocumentListItem,
  type DocumentListParams,
} from '../types/document'
import { formatDateTime } from '../utils/date'

type HistoryFilter = 'all' | 'review' | 'approved' | 'extracted' | 'failed'

interface HistoryState {
  key: string
  documents: DocumentListItem[]
  hasMore: boolean
  error?: string
  loadingMore?: boolean
  moreError?: string
}

const PAGE_SIZE = 50

const filters: Array<{ value: HistoryFilter; label: string }> = [
  { value: 'all', label: 'All' },
  { value: 'review', label: 'Review' },
  { value: 'approved', label: 'Approved' },
  { value: 'extracted', label: 'Extracted' },
  { value: 'failed', label: 'Failed' },
]

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

function getFilterParams(filter: HistoryFilter): DocumentListParams {
  switch (filter) {
    case 'review':
      return { requires_review: true }
    case 'approved':
      return { status: DocumentStatus.APPROVED }
    case 'extracted':
      return { status: DocumentStatus.EXTRACTED }
    case 'failed':
      return { status: DocumentStatus.FAILED }
    default:
      return {}
  }
}

export function DocumentsPage() {
  const location = useLocation()
  const navigate = useNavigate()
  const [filter, setFilter] = useState<HistoryFilter>('all')
  const [retry, setRetry] = useState(0)
  const [loadState, setLoadState] = useState<HistoryState | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<DocumentListItem | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const [toast, setToast] = useState<string | null>(() =>
    hasDeletionNotice(location.state) ? 'Document deleted' : null)
  const [toastWarning, setToastWarning] = useState<string | null>(() =>
    getDeletionWarning(location.state))
  const [toastVersion, setToastVersion] = useState(0)
  const moreRequestRef = useRef<AbortController | null>(null)
  const stateKey = `${filter}:${retry}`

  useEffect(() => {
    const controller = new AbortController()
    const request = {
      ...getFilterParams(filter),
      limit: PAGE_SIZE,
    }

    void getDocuments(request, controller.signal)
      .then((documents) => setLoadState({
        key: stateKey,
        documents,
        hasMore: documents.length === PAGE_SIZE,
      }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        setLoadState({
          key: stateKey,
          documents: [],
          hasMore: false,
          error: normalizeApiError(error).message,
        })
      })

    return () => {
      controller.abort()
      moreRequestRef.current?.abort()
    }
  }, [filter, retry, stateKey])

  useEffect(() => {
    if (!hasDeletionNotice(location.state)) return
    navigate(location.pathname, { replace: true, state: null })
  }, [location.key, location.pathname, location.state, navigate])

  const currentState = loadState?.key === stateKey ? loadState : undefined
  const loading = currentState === undefined
  const documents = currentState?.documents
  const loadError = currentState?.error

  function showToast(message: string, warning: string | null = null) {
    setToast(message)
    setToastWarning(warning)
    setToastVersion((current) => current + 1)
  }

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
      setLoadState((current) => current
        ? {
            ...current,
            documents: current.documents.filter(
              (document) => document.id !== deleteTarget.id,
            ),
          }
        : current)
      setDeleteTarget(null)
      showToast('Document deleted', response.warning ?? null)
    } catch (error: unknown) {
      setDeleteError(normalizeDocumentDeleteError(error).message)
    } finally {
      setDeleting(false)
    }
  }

  async function loadMore() {
    if (!currentState || currentState.loadingMore || !currentState.hasMore) return

    const controller = new AbortController()
    moreRequestRef.current?.abort()
    moreRequestRef.current = controller
    setLoadState((current) => current?.key === stateKey
      ? { ...current, loadingMore: true, moreError: undefined }
      : current)

    try {
      const nextDocuments = await getDocuments({
        ...getFilterParams(filter),
        limit: PAGE_SIZE,
        offset: currentState.documents.length,
      }, controller.signal)
      if (controller.signal.aborted) return
      setLoadState((current) => current?.key === stateKey
        ? {
            ...current,
            documents: [...current.documents, ...nextDocuments],
            hasMore: nextDocuments.length === PAGE_SIZE,
            loadingMore: false,
          }
        : current)
    } catch (error: unknown) {
      if (controller.signal.aborted) return
      setLoadState((current) => current?.key === stateKey
        ? {
            ...current,
            loadingMore: false,
            moreError: normalizeApiError(error).message,
          }
        : current)
    }
  }

  function closeMenu(details: HTMLDetailsElement | null) {
    if (details) details.open = false
  }

  return (
    <div className="page history-page">
      <section className="page-intro">
        <p>Your processed receipts, all in one place.</p>
      </section>

      <div aria-label="Filter documents" className="filter-chips" role="group">
        {filters.map(({ value, label }) => (
          <button
            aria-pressed={filter === value}
            className={`filter-chip${filter === value ? ' filter-chip--active' : ''}`}
            key={value}
            onClick={() => setFilter(value)}
            type="button"
          >
            {label}
          </button>
        ))}
      </div>

      {toast ? (
        <Toast
          key={toastVersion}
          message={toast}
          onDismiss={() => setToast(null)}
        />
      ) : null}
      {toastWarning ? (
        <Toast
          key={`warning-${toastVersion}`}
          message={toastWarning}
          onDismiss={() => setToastWarning(null)}
          variant="warning"
        />
      ) : null}

      {loading ? (
        <div aria-label="Loading document history" className="history-list">
          <div className="history-skeleton" />
          <div className="history-skeleton" />
          <div className="history-skeleton" />
        </div>
      ) : null}
      {!loading && loadError ? (
        <ErrorState
          message={loadError}
          onRetry={() => setRetry((current) => current + 1)}
        />
      ) : null}
      {!loading && documents?.length === 0 && !loadError ? (
        <EmptyState
          action={
            <Link className="primary-button" to="/scan">
              <Camera aria-hidden="true" size={18} />
              Scan Receipt
            </Link>
          }
          message={
            filter === 'all'
              ? 'Scan your first receipt to get started.'
              : 'No documents match this filter.'
          }
          title={filter === 'all' ? 'No documents yet' : 'No documents found'}
        />
      ) : null}

      {!loading && documents && documents.length > 0 ? (
        <>
          <div className="history-list">
            {documents.map((document) => (
              <article className="document-history-card" key={document.id}>
                <Link
                  aria-label={`Open ${document.original_filename}`}
                  className="document-history-card__main"
                  to={`/documents/${encodeURIComponent(document.id)}`}
                >
                  <span className="document-history-card__icon">
                    {document.content_type.startsWith('image/')
                      ? <FileImage aria-hidden="true" size={20} />
                      : <FileText aria-hidden="true" size={20} />}
                  </span>
                  <span className="document-history-card__content">
                    <strong title={document.original_filename}>
                      {document.original_filename}
                    </strong>
                    <span>{document.document_type}</span>
                    <span className="document-history-card__meta">
                      <StatusBadge status={document.status} />
                      <time dateTime={document.created_at}>
                        {formatDateTime(document.created_at)}
                      </time>
                    </span>
                  </span>
                  <ChevronRight
                    aria-hidden="true"
                    className="document-history-card__chevron"
                    size={19}
                  />
                </Link>
                <details className="document-history-card__menu">
                  <summary aria-label={`More actions for ${document.original_filename}`}>
                    <EllipsisVertical aria-hidden="true" size={20} />
                  </summary>
                  <div className="document-history-card__menu-content">
                    <Link
                      onClick={(event) => closeMenu(event.currentTarget.closest('details'))}
                      to={`/documents/${encodeURIComponent(document.id)}`}
                    >
                      View
                    </Link>
                    {document.status !== DocumentStatus.APPROVED ? (
                      <button
                        onClick={(event) => {
                          closeMenu(event.currentTarget.closest('details'))
                          requestDelete(document)
                        }}
                        type="button"
                      >
                        <Trash2 aria-hidden="true" size={16} />
                        Delete Document
                      </button>
                    ) : null}
                  </div>
                </details>
              </article>
            ))}
          </div>
          {currentState?.moreError ? (
            <ErrorState
              message={currentState.moreError}
              onRetry={() => void loadMore()}
              retryLabel="Try Again"
            />
          ) : null}
          {currentState?.hasMore ? (
            <button
              className="secondary-button history-load-more"
              disabled={currentState.loadingMore}
              onClick={() => void loadMore()}
              type="button"
            >
              {currentState.loadingMore ? 'Loading more…' : 'Load more'}
            </button>
          ) : null}
        </>
      ) : null}

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
