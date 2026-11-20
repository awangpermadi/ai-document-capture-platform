import {
  ArrowRight,
  Camera,
  CheckCircle2,
  ChevronRight,
  Clock3,
  FileImage,
  FileText,
  ScanLine,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { normalizeApiError } from '../api/client'
import { getDocuments } from '../api/documents'
import { EmptyState } from '../components/common/EmptyState'
import { ErrorState } from '../components/common/ErrorState'
import { StatusBadge } from '../components/common/StatusBadge'
import { DocumentStatus, type DocumentListItem } from '../types/document'
import { formatDateTime } from '../utils/date'

const HOME_DOCUMENT_LIMIT = 100

interface HomeLoadState {
  requestId: number
  documents?: DocumentListItem[]
  error?: string
}

export function HomePage() {
  const [requestId, setRequestId] = useState(0)
  const [loadState, setLoadState] = useState<HomeLoadState | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    void getDocuments({ limit: HOME_DOCUMENT_LIMIT }, controller.signal)
      .then((documents) => setLoadState({ requestId, documents }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        setLoadState({
          requestId,
          error: normalizeApiError(error).message,
        })
      })

    return () => controller.abort()
  }, [requestId])

  const loading = loadState?.requestId !== requestId
  const documents = loadState?.requestId === requestId
    ? loadState.documents
    : undefined
  const error = loadState?.requestId === requestId
    ? loadState.error
    : undefined
  const completeList = documents !== undefined
    && documents.length < HOME_DOCUMENT_LIMIT
  const needsReview = completeList
    ? documents?.filter((document) => document.requires_review).length ?? null
    : null
  const approved = completeList
    ? documents?.filter((document) => document.status === DocumentStatus.APPROVED).length ?? null
    : null

  return (
    <div className="page home-page">
      <section className="scan-hero">
        <span className="scan-hero__icon">
          <ScanLine aria-hidden="true" size={24} />
        </span>
        <div>
          <p className="eyebrow">RECEIPT CAPTURE</p>
          <h2>Scan your receipt</h2>
          <p>Turn a receipt into structured data in seconds.</p>
        </div>
        <Link className="primary-button scan-hero__button" to="/scan">
          <Camera aria-hidden="true" size={19} />
          Scan Receipt
        </Link>
        <span aria-hidden="true" className="scan-hero__decoration">
          <ScanLine size={120} strokeWidth={0.75} />
        </span>
      </section>

      {!loading && error ? (
        <ErrorState
          message={error}
          onRetry={() => setRequestId((current) => current + 1)}
        />
      ) : null}

      {!error ? (
        <section aria-labelledby="overview-title" className="home-section">
          <div className="section-heading">
            <h2 id="overview-title">Overview</h2>
          </div>
          {loading ? (
            <div aria-label="Loading document overview" className="overview-grid">
              <div className="overview-skeleton" />
              <div className="overview-skeleton" />
            </div>
          ) : null}
          {!loading && documents ? (
            <div className="overview-grid">
              <article className="overview-card overview-card--review">
                <span className="overview-card__icon">
                  <Clock3 aria-hidden="true" size={19} />
                </span>
                <div>
                  <span>Needs Review</span>
                  <strong>{needsReview ?? '—'}</strong>
                </div>
              </article>
              <article className="overview-card overview-card--approved">
                <span className="overview-card__icon">
                  <CheckCircle2 aria-hidden="true" size={19} />
                </span>
                <div>
                  <span>Approved</span>
                  <strong>{approved ?? '—'}</strong>
                </div>
              </article>
            </div>
          ) : null}
          {completeList === false && !loading ? (
            <p className="overview-footnote">
              Counts are shown only when the full document list is available.
            </p>
          ) : null}
        </section>
      ) : null}

      {!error ? (
        <section aria-labelledby="recent-documents-title" className="home-section">
          <div className="section-heading section-heading--action">
            <h2 id="recent-documents-title">Recent Documents</h2>
            <Link className="section-link" to="/documents">
              See all <ArrowRight aria-hidden="true" size={16} />
            </Link>
          </div>
          {loading ? (
            <div aria-label="Loading recent documents" className="history-list">
              <div className="history-skeleton" />
              <div className="history-skeleton" />
            </div>
          ) : null}
          {!loading && documents?.length === 0 ? (
            <EmptyState
              action={
                <Link className="primary-button" to="/scan">
                  <Camera aria-hidden="true" size={18} />
                  Scan Receipt
                </Link>
              }
              message="Scan your first receipt to get started."
              title="No documents yet"
            />
          ) : null}
          {!loading && documents && documents.length > 0 ? (
            <div className="history-list">
              {documents.slice(0, 5).map((document) => (
                <Link
                  className="history-card"
                  key={document.id}
                  to={`/documents/${encodeURIComponent(document.id)}`}
                >
                  <span className="history-card__file-icon">
                    {document.content_type.startsWith('image/')
                      ? <FileImage aria-hidden="true" size={19} />
                      : <FileText aria-hidden="true" size={19} />}
                  </span>
                  <span className="history-card__content">
                    <strong title={document.original_filename}>
                      {document.original_filename}
                    </strong>
                    <span>{formatDateTime(document.created_at)}</span>
                    <StatusBadge status={document.status} />
                  </span>
                  <ChevronRight aria-hidden="true" className="history-card__chevron" size={19} />
                </Link>
              ))}
            </div>
          ) : null}
        </section>
      ) : null}
    </div>
  )
}
