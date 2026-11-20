import { ArrowRight, CheckCircle2, Clock3, FileStack, Upload } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { normalizeApiError } from '../api/client'
import { getDocuments } from '../api/documents'
import { EmptyState } from '../components/common/EmptyState'
import { ErrorState } from '../components/common/ErrorState'
import { LoadingState } from '../components/common/LoadingState'
import { StatusBadge } from '../components/common/StatusBadge'
import { DocumentStatus, type DocumentListItem } from '../types/document'
import { formatDateTime } from '../utils/date'

const DASHBOARD_DOCUMENT_LIMIT = 100

interface DashboardLoadState {
  requestId: number
  documents?: DocumentListItem[]
  error?: string
}

export function DashboardPage() {
  const [requestId, setRequestId] = useState(0)
  const [loadState, setLoadState] = useState<DashboardLoadState | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    void getDocuments(
      { limit: DASHBOARD_DOCUMENT_LIMIT },
      controller.signal,
    )
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
  const countsAreComplete =
    documents !== undefined && documents.length < DASHBOARD_DOCUMENT_LIMIT
  const needsReview = documents?.filter(
    (document) => document.requires_review,
  ).length
  const approved = documents?.filter(
    (document) => document.status === DocumentStatus.APPROVED,
  ).length

  return (
    <div className="page dashboard-page">
      <section className="page-intro">
        <div>
          <p className="eyebrow">DOCUMENT OPERATIONS</p>
          <h2>Overview</h2>
          <p>Monitor captured documents and continue receipt reviews.</p>
        </div>
        <Link className="button button--primary" to="/upload">
          <Upload aria-hidden="true" size={17} />
          Upload document
        </Link>
      </section>

      {loading ? <LoadingState label="Loading your documents…" /> : null}
      {!loading && error ? (
        <ErrorState
          message={error}
          onRetry={() => setRequestId((current) => current + 1)}
        />
      ) : null}

      {!loading && !error && documents ? (
        <>
          {countsAreComplete ? (
            <section aria-label="Document status overview" className="dashboard-stats">
              <article className="dashboard-stat">
                <span className="dashboard-stat__icon dashboard-stat__icon--blue">
                  <FileStack aria-hidden="true" size={18} />
                </span>
                <div>
                  <span>Total documents</span>
                  <strong>{documents.length}</strong>
                </div>
              </article>
              <article className="dashboard-stat">
                <span className="dashboard-stat__icon dashboard-stat__icon--amber">
                  <Clock3 aria-hidden="true" size={18} />
                </span>
                <div>
                  <span>Needs review</span>
                  <strong>{needsReview}</strong>
                </div>
              </article>
              <article className="dashboard-stat">
                <span className="dashboard-stat__icon dashboard-stat__icon--green">
                  <CheckCircle2 aria-hidden="true" size={18} />
                </span>
                <div>
                  <span>Approved</span>
                  <strong>{approved}</strong>
                </div>
              </article>
            </section>
          ) : documents.length >= DASHBOARD_DOCUMENT_LIMIT ? (
            <p className="dashboard-note">
              Showing the latest {DASHBOARD_DOCUMENT_LIMIT} documents. The API does not
              provide a total count, so status totals are not shown.
            </p>
          ) : null}

          <section aria-labelledby="recent-documents-title" className="content-card">
            <div className="content-card__heading">
              <div>
                <h2 id="recent-documents-title">Recent documents</h2>
                <p>Most recently updated receipts in your workspace.</p>
              </div>
              <Link className="text-link" to="/documents">
                View all <ArrowRight aria-hidden="true" size={16} />
              </Link>
            </div>
            {documents.length === 0 ? (
              <EmptyState
                action={
                  <Link className="button button--primary" to="/upload">
                    <Upload aria-hidden="true" size={16} />
                    Upload a document
                  </Link>
                }
                message="Documents will appear here after they are processed."
                title="No documents yet"
              />
            ) : (
              <div className="table-scroll">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th scope="col">File name</th>
                      <th scope="col">Document type</th>
                      <th scope="col">Status</th>
                      <th scope="col">Review</th>
                      <th scope="col">Created</th>
                      <th scope="col">Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {documents.slice(0, 5).map((document) => (
                      <tr key={document.id}>
                        <td className="data-table__filename" title={document.original_filename}>
                          {document.original_filename}
                        </td>
                        <td>{document.document_type}</td>
                        <td><StatusBadge status={document.status} /></td>
                        <td>{document.requires_review ? 'Required' : 'Not required'}</td>
                        <td>{formatDateTime(document.created_at)}</td>
                        <td>
                          <Link
                            className="table-action"
                            to={`/documents/${encodeURIComponent(document.id)}`}
                          >
                            View <ArrowRight aria-hidden="true" size={15} />
                          </Link>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      ) : null}
    </div>
  )
}
