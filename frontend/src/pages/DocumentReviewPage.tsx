import {
  ArrowLeft,
  Check,
  ChevronDown,
  FileImage,
  FileText,
  LoaderCircle,
  Plus,
  Save,
  Trash2,
} from 'lucide-react'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import {
  normalizeApiError,
  normalizeDocumentDeleteError,
} from '../api/client'
import {
  approveDocument,
  deleteDocument,
  getDocument,
  updateReceipt,
} from '../api/documents'
import { DeleteDocumentDialog } from '../components/common/DeleteDocumentDialog'
import { ErrorState } from '../components/common/ErrorState'
import { LoadingState } from '../components/common/LoadingState'
import { StatusBadge } from '../components/common/StatusBadge'
import { ReceiptItems } from '../components/receipt/ReceiptItems'
import { ReceiptSummary } from '../components/receipt/ReceiptSummary'
import {
  DocumentStatus,
  type DocumentDetail,
} from '../types/document'
import type { ReceiptCorrectionRequest } from '../types/receipt'
import { formatDateTime } from '../utils/date'

interface EditableItem {
  id: string | null
  description_raw: string
  description_normalized: string
  quantity: number | null
  unit_price: number | null
  total_price: number | null
}

interface CorrectionForm {
  merchant: {
    name: string
    address: string
    phone: string
  }
  transaction: {
    date: string
    time: string
    subtotal: number | null
    discount: number | null
    tax: number | null
    tip: number | null
    total: number | null
    cash: number | null
    change: number | null
    currency: string
  }
  items: EditableItem[]
}

type TransactionAmountField =
  | 'subtotal'
  | 'discount'
  | 'tax'
  | 'tip'
  | 'total'
  | 'cash'
  | 'change'
type ItemAmountField = 'quantity' | 'unit_price' | 'total_price'
type ValidationErrors = Record<string, string>

interface ReviewLoadState {
  key: string
  document?: DocumentDetail
  error?: string
}

const transactionFields: Array<{
  key: TransactionAmountField
  label: string
}> = [
  { key: 'subtotal', label: 'Subtotal' },
  { key: 'discount', label: 'Discount' },
  { key: 'tax', label: 'Tax' },
  { key: 'tip', label: 'Tip' },
  { key: 'total', label: 'Total' },
  { key: 'cash', label: 'Cash' },
  { key: 'change', label: 'Change' },
]

function createCorrectionForm(document: DocumentDetail): CorrectionForm {
  const { merchant, transaction, items } = document.receipt
  return {
    merchant: {
      name: merchant.name ?? '',
      address: merchant.address ?? '',
      phone: merchant.phone ?? '',
    },
    transaction: {
      date: transaction.date ?? '',
      time: transaction.time?.slice(0, 5) ?? '',
      subtotal: transaction.subtotal,
      discount: transaction.discount,
      tax: transaction.tax,
      tip: transaction.tip,
      total: transaction.total,
      cash: transaction.cash,
      change: transaction.change,
      currency: transaction.currency ?? 'IDR',
    },
    items: items.map((item) => ({
      id: item.id,
      description_raw: item.description_raw ?? '',
      description_normalized: item.description_normalized ?? '',
      quantity: item.quantity,
      unit_price: item.unit_price,
      total_price: item.total_price,
    })),
  }
}

function validateCorrection(form: CorrectionForm): ValidationErrors {
  const errors: ValidationErrors = {}
  for (const field of transactionFields) {
    const value = form.transaction[field.key]
    if (value !== null && (!Number.isFinite(value) || value < 0)) {
      errors[`transaction.${field.key}`] =
        `${field.label} must be a non-negative number.`
    }
  }

  form.items.forEach((item, index) => {
    const hasRaw = Boolean(item.description_raw.trim())
    const hasNormalized = Boolean(item.description_normalized.trim())
    if (!hasRaw && !hasNormalized) {
      errors[`items.${index}.description`] =
        'Enter a description in at least one description field.'
    }
    if (item.quantity !== null
      && (!Number.isFinite(item.quantity) || item.quantity <= 0)) {
      errors[`items.${index}.quantity`] =
        'Quantity must be greater than zero.'
    }
    for (const field of ['unit_price', 'total_price'] as const) {
      const value = item[field]
      if (value !== null && (!Number.isFinite(value) || value < 0)) {
        errors[`items.${index}.${field}`] =
          'Amount must be a non-negative number.'
      }
    }
  })

  return errors
}

function nullableText(value: string): string | null {
  const trimmed = value.trim()
  return trimmed ? trimmed : null
}

function numberFromInput(value: string): number | null {
  if (value === '') return null
  return Number(value)
}

function LoadingButton({ label }: { label: string }) {
  return (
    <>
      <LoaderCircle aria-hidden="true" className="loading-icon" size={17} />
      {label}
    </>
  )
}

export function DocumentReviewPage() {
  const { id } = useParams<{ id: string }>()
  const [retryCount, setRetryCount] = useState(0)
  const [loadState, setLoadState] = useState<ReviewLoadState | null>(null)
  const [form, setForm] = useState<CorrectionForm | null>(null)
  const [validationErrors, setValidationErrors] = useState<ValidationErrors>({})
  const [actionError, setActionError] = useState<string | null>(null)
  const [successMessage, setSuccessMessage] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [approving, setApproving] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const [approvalOpen, setApprovalOpen] = useState(false)
  const dialogRef = useRef<HTMLDialogElement>(null)
  const navigate = useNavigate()
  const stateKey = `${id ?? ''}:${retryCount}`

  useEffect(() => {
    if (!id) return
    const controller = new AbortController()
    void getDocument(id, controller.signal)
      .then((document) => setLoadState({ key: stateKey, document }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        setLoadState({
          key: stateKey,
          error: normalizeApiError(error).message,
        })
      })

    return () => controller.abort()
  }, [id, stateKey])

  useEffect(() => {
    const dialog = dialogRef.current
    if (!dialog) return
    if (approvalOpen && !dialog.open) dialog.showModal()
    if (!approvalOpen && dialog.open) dialog.close()
  }, [approvalOpen])

  const loading = loadState?.key !== stateKey
  const document = loadState?.key === stateKey ? loadState.document : undefined
  const loadError = loadState?.key === stateKey ? loadState.error : undefined
  const isApproved = document?.status === DocumentStatus.APPROVED
  const canEdit = Boolean(document && !isApproved)

  function startEditing() {
    if (!document) return
    setForm(createCorrectionForm(document))
    setValidationErrors({})
    setActionError(null)
    setSuccessMessage(null)
  }

  function cancelEditing() {
    setForm(null)
    setValidationErrors({})
  }

  function updateMerchant(field: keyof CorrectionForm['merchant'], value: string) {
    setForm((current) => current
      ? { ...current, merchant: { ...current.merchant, [field]: value } }
      : current)
  }

  function updateTransactionText(
    field: 'date' | 'time' | 'currency',
    value: string,
  ) {
    setForm((current) => current
      ? { ...current, transaction: { ...current.transaction, [field]: value } }
      : current)
  }

  function updateTransactionAmount(field: TransactionAmountField, value: string) {
    setForm((current) => current
      ? {
          ...current,
          transaction: {
            ...current.transaction,
            [field]: numberFromInput(value),
          },
        }
      : current)
  }

  function updateItemText(
    index: number,
    field: 'description_raw' | 'description_normalized',
    value: string,
  ) {
    setForm((current) => current
      ? {
          ...current,
          items: current.items.map((item, itemIndex) =>
            itemIndex === index ? { ...item, [field]: value } : item),
        }
      : current)
  }

  function updateItemAmount(
    index: number,
    field: ItemAmountField,
    value: string,
  ) {
    setForm((current) => current
      ? {
          ...current,
          items: current.items.map((item, itemIndex) =>
            itemIndex === index
              ? { ...item, [field]: numberFromInput(value) }
              : item),
        }
      : current)
  }

  function addItem() {
    setForm((current) => current
      ? {
          ...current,
          items: [
            ...current.items,
            {
              id: null,
              description_raw: '',
              description_normalized: '',
              quantity: 1,
              unit_price: null,
              total_price: null,
            },
          ],
        }
      : current)
  }

  function removeItem(index: number) {
    setForm((current) => current
      ? {
          ...current,
          items: current.items.filter((_, itemIndex) => itemIndex !== index),
        }
      : current)
  }

  async function reloadAfterAction(updated: DocumentDetail) {
    if (!id) return
    setLoadState({ key: stateKey, document: updated })
    try {
      const freshDocument = await getDocument(id)
      setLoadState({ key: stateKey, document: freshDocument })
    } catch (error: unknown) {
      setActionError(
        `Your change was saved, but the latest document could not be reloaded. ${normalizeApiError(error).message}`,
      )
    }
  }

  async function saveCorrection(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!id || !form || saving) return

    const errors = validateCorrection(form)
    setValidationErrors(errors)
    setActionError(null)
    setSuccessMessage(null)
    if (Object.keys(errors).length > 0) return

    const correction: ReceiptCorrectionRequest = {
      merchant: {
        name: nullableText(form.merchant.name),
        address: nullableText(form.merchant.address),
        phone: nullableText(form.merchant.phone),
      },
      transaction: {
        date: nullableText(form.transaction.date),
        time: nullableText(form.transaction.time),
        subtotal: form.transaction.subtotal,
        discount: form.transaction.discount,
        tax: form.transaction.tax,
        tip: form.transaction.tip,
        total: form.transaction.total,
        cash: form.transaction.cash,
        change: form.transaction.change,
        currency: form.transaction.currency.trim() || 'IDR',
      },
      items: form.items.map((item) => ({
        id: item.id,
        description_raw: nullableText(item.description_raw),
        description_normalized: nullableText(item.description_normalized),
        quantity: item.quantity,
        unit_price: item.unit_price,
        total_price: item.total_price,
      })),
    }

    setSaving(true)
    try {
      const updated = await updateReceipt(id, correction)
      setForm(null)
      setValidationErrors({})
      setSuccessMessage('Receipt corrections saved.')
      await reloadAfterAction(updated)
    } catch (error: unknown) {
      setActionError(normalizeApiError(error).message)
    } finally {
      setSaving(false)
    }
  }

  async function confirmApproval() {
    if (!id || approving) return
    setApproving(true)
    setActionError(null)
    setSuccessMessage(null)
    try {
      const result = await approveDocument(id, { confirmation: true })
      setApprovalOpen(false)
      setSuccessMessage('Receipt approved. Its data is now read-only.')
      if (document) {
        await reloadAfterAction({
          ...document,
          status: DocumentStatus.APPROVED,
          requires_review: false,
          approved_at: result.approved_at,
          reviewed_at: result.reviewed_at,
          updated_at: result.updated_at,
          review_reasons: [],
        })
      } else {
        setRetryCount((current) => current + 1)
      }
    } catch (error: unknown) {
      setActionError(normalizeApiError(error).message)
    } finally {
      setApproving(false)
    }
  }

  async function confirmDelete() {
    if (!id || !document || isApproved || deleting) return
    setDeleting(true)
    setDeleteError(null)
    try {
      const response = await deleteDocument(id)
      setDeleteOpen(false)
      navigate('/documents', {
        state: {
          documentDeleted: true,
          deletionWarning: response.warning,
        },
      })
    } catch (error: unknown) {
      setDeleteError(normalizeDocumentDeleteError(error).message)
    } finally {
      setDeleting(false)
    }
  }

  if (!id) {
    return <ErrorState message="A document identifier is required." />
  }

  return (
    <div className="page review-page">
      <Link className="back-link" to="/documents">
        <ArrowLeft aria-hidden="true" size={18} />
        Back
      </Link>

      {loading ? <LoadingState label="Loading receipt review…" /> : null}
      {!loading && loadError ? (
        <ErrorState
          message={loadError}
          onRetry={() => setRetryCount((current) => current + 1)}
        />
      ) : null}

      {!loading && document ? (
        <>
          <section className="review-title">
            <div className="review-title__text">
              <p className="eyebrow">DOCUMENT</p>
              <h1>Receipt Review</h1>
              <p className="review-title__filename" title={document.original_filename}>
                {document.original_filename}
              </p>
            </div>
            <StatusBadge status={document.status} />
          </section>

          {successMessage ? (
            <div className="inline-notice inline-notice--success" role="status">
              <Check aria-hidden="true" size={17} />
              <span>{successMessage}</span>
            </div>
          ) : null}
          {actionError ? (
            <ErrorState
              message={actionError}
              onRetry={() => setRetryCount((current) => current + 1)}
              title="Action could not be completed"
            />
          ) : null}

          {document.requires_review ? (
            <section className="review-notice" aria-label="Review required notice">
              <strong>Review required</strong>
              {document.review_reasons.length > 0 ? (
                <ul>
                  {document.review_reasons.map((reason, index) => (
                    <li key={`${reason}-${index}`}>{reason}</li>
                  ))}
                </ul>
              ) : (
                <p>Please check the extracted receipt details.</p>
              )}
            </section>
          ) : null}

          <section aria-labelledby="document-info-title" className="mobile-card">
            <div className="section-title">
              <h2 id="document-info-title">Document information</h2>
            </div>
            <dl className="info-list">
              <div><dt>File name</dt><dd>{document.original_filename}</dd></div>
              <div><dt>Document type</dt><dd>{document.document_type}</dd></div>
              {document.extraction_method ? (
                <div><dt>Extraction method</dt><dd>{document.extraction_method}</dd></div>
              ) : null}
              <div><dt>Created</dt><dd>{formatDateTime(document.created_at)}</dd></div>
              {document.approved_at ? (
                <div><dt>Approved</dt><dd>{formatDateTime(document.approved_at)}</dd></div>
              ) : null}
            </dl>
            <div className="original-document">
              <span className="original-document__icon">
                {document.content_type.startsWith('image/')
                  ? <FileImage aria-hidden="true" size={18} />
                  : <FileText aria-hidden="true" size={18} />}
              </span>
              <div>
                <strong>Original receipt</strong>
                <span>Original receipt preview will be available when file access is exposed.</span>
              </div>
              <ChevronDown aria-hidden="true" className="original-document__placeholder" size={17} />
            </div>
          </section>

          {form && canEdit ? (
            <form className="review-form" onSubmit={(event) => void saveCorrection(event)}>
              <section aria-labelledby="merchant-edit-title" className="mobile-card">
                <div className="section-title"><h2 id="merchant-edit-title">Merchant information</h2></div>
                <div className="edit-field-list">
                  {([
                    ['name', 'Merchant name'],
                    ['address', 'Address'],
                    ['phone', 'Phone'],
                  ] as const).map(([field, label]) => (
                    <label className="form-field" key={field}>
                      <span>{label}</span>
                      <input
                        autoComplete="off"
                        onChange={(event) => updateMerchant(field, event.target.value)}
                        value={form.merchant[field]}
                      />
                    </label>
                  ))}
                </div>
              </section>

              <section aria-labelledby="transaction-edit-title" className="mobile-card">
                <div className="section-title"><h2 id="transaction-edit-title">Transaction information</h2></div>
                <div className="edit-field-list edit-field-list--two">
                  <label className="form-field">
                    <span>Date</span>
                    <input
                      onChange={(event) => updateTransactionText('date', event.target.value)}
                      type="date"
                      value={form.transaction.date}
                    />
                  </label>
                  <label className="form-field">
                    <span>Time</span>
                    <input
                      onChange={(event) => updateTransactionText('time', event.target.value)}
                      type="time"
                      value={form.transaction.time}
                    />
                  </label>
                  {transactionFields.map(({ key, label }) => {
                    const error = validationErrors[`transaction.${key}`]
                    return (
                      <label className="form-field" key={key}>
                        <span>{label}</span>
                        <input
                          aria-describedby={error ? `transaction-${key}-error` : undefined}
                          aria-invalid={Boolean(error)}
                          min="0"
                          onChange={(event) => updateTransactionAmount(key, event.target.value)}
                          step="any"
                          type="number"
                          value={form.transaction[key] ?? ''}
                        />
                        {error ? (
                          <small className="field-error" id={`transaction-${key}-error`}>{error}</small>
                        ) : null}
                      </label>
                    )
                  })}
                  <label className="form-field">
                    <span>Currency</span>
                    <input
                      autoCapitalize="characters"
                      maxLength={10}
                      onChange={(event) => updateTransactionText('currency', event.target.value)}
                      value={form.transaction.currency}
                    />
                  </label>
                </div>
              </section>

              <section aria-labelledby="items-edit-title" className="mobile-card">
                <div className="section-title section-title--action">
                  <h2 id="items-edit-title">Receipt items</h2>
                  <button className="text-button" onClick={addItem} type="button">
                    <Plus aria-hidden="true" size={16} /> Add item
                  </button>
                </div>
                {form.items.length === 0 ? (
                  <p className="form-hint">No items yet. Add a receipt item to continue.</p>
                ) : null}
                <div className="edit-items-list">
                  {form.items.map((item, index) => {
                    const descriptionError = validationErrors[`items.${index}.description`]
                    return (
                      <article className="edit-item-card" key={item.id ?? `new-${index}`}>
                        <div className="edit-item-card__heading">
                          <strong>Item {index + 1}</strong>
                          <button
                            aria-label={`Remove item ${index + 1}`}
                            className="icon-action icon-action--danger"
                            onClick={() => removeItem(index)}
                            type="button"
                          >
                            <Trash2 aria-hidden="true" size={18} />
                          </button>
                        </div>
                        <div className="edit-field-list">
                          <label className="form-field">
                            <span>Receipt description</span>
                            <input
                              aria-describedby={descriptionError ? `item-${index}-description-error` : undefined}
                              aria-invalid={Boolean(descriptionError)}
                              onChange={(event) => updateItemText(index, 'description_raw', event.target.value)}
                              value={item.description_raw}
                            />
                          </label>
                          <label className="form-field">
                            <span>Normalized description</span>
                            <input
                              onChange={(event) => updateItemText(index, 'description_normalized', event.target.value)}
                              value={item.description_normalized}
                            />
                            {descriptionError ? (
                              <small className="field-error" id={`item-${index}-description-error`}>
                                {descriptionError}
                              </small>
                            ) : null}
                          </label>
                          <div className="edit-field-list--two">
                            {([
                              ['quantity', 'Quantity', '0'],
                              ['unit_price', 'Unit price', '0'],
                              ['total_price', 'Total price', '0'],
                            ] as const).map(([field, label, min]) => {
                              const error = validationErrors[`items.${index}.${field}`]
                              return (
                                <label className="form-field" key={field}>
                                  <span>{label}</span>
                                  <input
                                    aria-describedby={error ? `item-${index}-${field}-error` : undefined}
                                    aria-invalid={Boolean(error)}
                                    min={field === 'quantity' ? '0.000001' : min}
                                    onChange={(event) => updateItemAmount(index, field, event.target.value)}
                                    step="any"
                                    type="number"
                                    value={item[field] ?? ''}
                                  />
                                  {error ? (
                                    <small className="field-error" id={`item-${index}-${field}-error`}>{error}</small>
                                  ) : null}
                                </label>
                              )
                            })}
                          </div>
                        </div>
                      </article>
                    )
                  })}
                </div>
              </section>

              <div className="review-action-bar">
                <button
                  className="mobile-button mobile-button--secondary"
                  disabled={saving}
                  onClick={cancelEditing}
                  type="button"
                >
                  Cancel
                </button>
                <button
                  className="mobile-button mobile-button--primary"
                  disabled={saving}
                  type="submit"
                >
                  {saving ? <LoadingButton label="Saving…" /> : <><Save aria-hidden="true" size={18} />Save corrections</>}
                </button>
              </div>
            </form>
          ) : (
            <>
              <ReceiptSummary receipt={document.receipt} />
              <ReceiptItems
                items={document.receipt.items}
                transaction={document.receipt.transaction}
              />
            </>
          )}

          {!isApproved ? (
            <section aria-label="Review actions" className="review-actions">
              {!form ? (
                <button
                  className="mobile-button mobile-button--secondary"
                  onClick={startEditing}
                  type="button"
                >
                  Edit receipt
                </button>
              ) : null}
              {!form ? (
                <button
                  className="mobile-button mobile-button--primary"
                  onClick={() => setApprovalOpen(true)}
                  type="button"
                >
                  <Check aria-hidden="true" size={18} />
                  Approve
                </button>
              ) : null}
            </section>
          ) : null}
          {!isApproved ? (
            <div className="review-delete-action">
              <button
                className="button button--secondary review-delete-action__button"
                onClick={() => {
                  setDeleteError(null)
                  setDeleteOpen(true)
                }}
                type="button"
              >
                <Trash2 aria-hidden="true" size={17} />
                Delete Document
              </button>
            </div>
          ) : null}
        </>
      ) : null}

      <DeleteDocumentDialog
        deleting={deleting}
        documentName={document?.original_filename ?? ''}
        errorMessage={deleteError}
        onCancel={() => {
          if (!deleting) {
            setDeleteError(null)
            setDeleteOpen(false)
          }
        }}
        onConfirm={() => void confirmDelete()}
        open={deleteOpen && Boolean(document) && !isApproved}
      />

      <dialog
        aria-labelledby="approval-dialog-title"
        className="approval-dialog"
        onCancel={(event) => {
          event.preventDefault()
          setApprovalOpen(false)
        }}
        onClose={() => setApprovalOpen(false)}
        ref={dialogRef}
      >
        <div className="approval-dialog__icon"><Check aria-hidden="true" size={23} /></div>
        <h2 id="approval-dialog-title">Approve this receipt?</h2>
        <p>Approved receipt data will become read-only and can no longer be corrected.</p>
        <div className="approval-dialog__actions">
          <button
            className="mobile-button mobile-button--secondary"
            disabled={approving}
            onClick={() => setApprovalOpen(false)}
            type="button"
          >
            Cancel
          </button>
          <button
            className="mobile-button mobile-button--primary"
            disabled={approving}
            onClick={() => void confirmApproval()}
            type="button"
          >
            {approving ? <LoadingButton label="Approving…" /> : 'Approve receipt'}
          </button>
        </div>
      </dialog>
    </div>
  )
}
