import { LoaderCircle, Trash2 } from 'lucide-react'
import { useEffect, useRef, type SyntheticEvent } from 'react'

interface DeleteDocumentDialogProps {
  open: boolean
  documentName: string
  deleting: boolean
  errorMessage: string | null
  onCancel: () => void
  onConfirm: () => void
}

export function DeleteDocumentDialog({
  open,
  documentName,
  deleting,
  errorMessage,
  onCancel,
  onConfirm,
}: DeleteDocumentDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null)

  useEffect(() => {
    const dialog = dialogRef.current
    if (!dialog) return
    if (open && !dialog.open) dialog.showModal()
    if (!open && dialog.open) dialog.close()
  }, [open])

  function cancel(event?: SyntheticEvent<HTMLDialogElement>) {
    event?.preventDefault()
    if (!deleting) onCancel()
  }

  return (
    <dialog
      aria-describedby={
        errorMessage
          ? 'delete-document-message delete-document-error'
          : 'delete-document-message'
      }
      aria-labelledby="delete-document-title"
      className="delete-document-dialog"
      onCancel={cancel}
      onClose={() => {
        if (!deleting) onCancel()
      }}
      ref={dialogRef}
    >
      <h2 id="delete-document-title">Delete document?</h2>
      <p id="delete-document-message">
        This document and its extracted receipt data will be permanently deleted.
        This action cannot be undone.
      </p>
      <p className="delete-document-dialog__filename" title={documentName}>
        {documentName}
      </p>
      {errorMessage ? (
        <p className="delete-document-dialog__error" id="delete-document-error" role="alert">
          {errorMessage}
        </p>
      ) : null}
      {deleting ? (
        <p className="delete-document-dialog__progress" role="status">
          Deleting document…
        </p>
      ) : null}
      <div aria-busy={deleting} className="delete-document-dialog__actions">
        <button
          autoFocus
          className="mobile-button mobile-button--secondary"
          disabled={deleting}
          onClick={() => cancel()}
          type="button"
        >
          Cancel
        </button>
        <button
          aria-label={
            deleting
              ? `Deleting ${documentName}`
              : `Permanently delete ${documentName}`
          }
          className="mobile-button mobile-button--danger"
          disabled={deleting}
          onClick={onConfirm}
          type="button"
        >
          {deleting ? (
            <>
              <LoaderCircle aria-hidden="true" className="loading-icon" size={17} />
              Deleting…
            </>
          ) : (
            <>
              <Trash2 aria-hidden="true" size={17} />
              Delete
            </>
          )}
        </button>
      </div>
    </dialog>
  )
}
