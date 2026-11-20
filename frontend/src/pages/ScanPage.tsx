import {
  ArrowUpFromLine,
  Camera,
  FileImage,
  FileText,
  ImagePlus,
  RefreshCw,
  ScanLine,
  Trash2,
} from 'lucide-react'
import {
  useEffect,
  useRef,
  useState,
  type ChangeEvent,
  type RefObject,
} from 'react'
import { useNavigate } from 'react-router-dom'
import { normalizeApiError } from '../api/client'
import { processDocument } from '../api/documents'
import { ErrorState } from '../components/common/ErrorState'

const MAX_FILE_SIZE = 10 * 1024 * 1024

const MIME_TYPES_BY_EXTENSION: Record<string, string> = {
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.png': 'image/png',
  '.pdf': 'application/pdf',
}

const ALLOWED_MIME_TYPES = new Set([
  'image/jpeg',
  'image/png',
  'application/pdf',
])

function getFileExtension(filename: string): string {
  const lastDotIndex = filename.lastIndexOf('.')
  return lastDotIndex < 0 ? '' : filename.slice(lastDotIndex).toLowerCase()
}

function isImageFile(file: File): boolean {
  const extension = getFileExtension(file.name)
  return file.type.startsWith('image/')
    || extension === '.jpg'
    || extension === '.jpeg'
    || extension === '.png'
}

function isPdfFile(file: File): boolean {
  const extension = getFileExtension(file.name)
  return extension === '.pdf'
    ? !file.type || file.type === 'application/pdf'
    : !extension && file.type === 'application/pdf'
}

function validateFile(file: File): string | null {
  if (!file.size) return 'This file is empty. Choose another receipt.'
  if (file.size > MAX_FILE_SIZE) return 'This file is larger than 10 MB.'

  const extension = getFileExtension(file.name)
  const expectedMime = MIME_TYPES_BY_EXTENSION[extension]
  if (extension && !expectedMime) {
    return 'Unsupported file format. Choose a JPG, JPEG, PNG, or PDF.'
  }
  if (file.type && !ALLOWED_MIME_TYPES.has(file.type)) {
    return 'Unsupported file format. Choose a JPG, JPEG, PNG, or PDF.'
  }
  if (expectedMime && file.type && file.type !== expectedMime) {
    return 'The file extension and file type do not match.'
  }
  if (!expectedMime && !file.type) {
    return 'The file type could not be determined. Choose a JPG, JPEG, PNG, or PDF.'
  }
  return null
}

function formatFileSize(size: number): string {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / (1024 * 1024)).toFixed(2)} MB`
}

function processingErrorMessage(error: unknown): string {
  const apiError = normalizeApiError(error)
  switch (apiError.status) {
    case 400:
      return 'Invalid or empty document. Choose a valid receipt and try again.'
    case 413:
      return 'This file is larger than 10 MB.'
    case 415:
      return 'Unsupported file format. Choose a JPG, JPEG, PNG, or PDF.'
    case 422:
      return 'The receipt could not be processed or validated. Try a clearer image.'
    case 500:
      return 'The document could not be saved. Please try again.'
    case 502:
      return 'The AI document processing service is temporarily unavailable.'
    default:
      return apiError.message
  }
}

interface FilePickerProps {
  accept: string
  capture?: 'environment'
  inputRef: RefObject<HTMLInputElement | null>
  label: string
  onChange: (event: ChangeEvent<HTMLInputElement>) => void
}

function FilePicker({
  accept,
  capture,
  inputRef,
  label,
  onChange,
}: FilePickerProps) {
  return (
    <input
      accept={accept}
      aria-label={label}
      className="visually-hidden"
      capture={capture}
      onChange={onChange}
      ref={inputRef}
      tabIndex={-1}
      type="file"
    />
  )
}

export function ScanPage() {
  const navigate = useNavigate()
  const cameraInputRef = useRef<HTMLInputElement>(null)
  const galleryInputRef = useRef<HTMLInputElement>(null)
  const pdfInputRef = useRef<HTMLInputElement>(null)
  const submitLock = useRef(false)
  const previewUrlRef = useRef<string | null>(null)
  const [file, setFile] = useState<File | null>(null)
  const [isProcessing, setIsProcessing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)

  const validationError = file ? validateFile(file) : null
  const isImage = Boolean(file && isImageFile(file))
  const isPdf = Boolean(file && isPdfFile(file))

  useEffect(() => () => {
    if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current)
  }, [])

  function chooseFile(nextFile: File | null) {
    if (previewUrlRef.current) {
      URL.revokeObjectURL(previewUrlRef.current)
    }
    previewUrlRef.current =
      nextFile && isImageFile(nextFile) ? URL.createObjectURL(nextFile) : null
    setPreviewUrl(previewUrlRef.current)
    setFile(nextFile)
    setError(null)
  }

  function handlePickerChange(event: ChangeEvent<HTMLInputElement>) {
    const selectedFile = event.currentTarget.files?.[0]
    if (selectedFile) chooseFile(selectedFile)
    event.currentTarget.value = ''
  }

  function clearFile() {
    chooseFile(null)
  }

  async function submit() {
    if (!file || submitLock.current) return
    const invalidReason = validateFile(file)
    if (invalidReason) {
      setError(invalidReason)
      return
    }

    submitLock.current = true
    setError(null)
    setIsProcessing(true)
    try {
      const result = await processDocument(file)
      navigate(`/documents/${encodeURIComponent(result.document_id)}`, {
        state: { documentProcessed: true },
      })
    } catch (requestError: unknown) {
      setError(processingErrorMessage(requestError))
    } finally {
      submitLock.current = false
      setIsProcessing(false)
    }
  }

  return (
    <div className="page scan-page">
      {isProcessing ? (
        <section aria-live="polite" className="processing-screen" role="status">
          <span className="processing-screen__icon">
            <ScanLine aria-hidden="true" className="processing-scan-icon" size={48} />
          </span>
          <h2>Analyzing receipt</h2>
          <p>AI is reading your document.</p>
          <ol className="processing-steps">
            <li><span className="processing-step__dot" />Uploading document</li>
            <li><span className="processing-step__dot" />Reading receipt</li>
            <li><span className="processing-step__dot" />Preparing results</li>
          </ol>
          <small>These are visual steps, not live progress updates.</small>
        </section>
      ) : (
        <>
          <FilePicker
            accept="image/*"
            capture="environment"
            inputRef={cameraInputRef}
            label="Take a receipt photo using the rear camera"
            onChange={handlePickerChange}
          />
          <FilePicker
            accept="image/jpeg,image/png"
            inputRef={galleryInputRef}
            label="Choose a JPG or PNG from your gallery"
            onChange={handlePickerChange}
          />
          <FilePicker
            accept=".pdf,application/pdf"
            inputRef={pdfInputRef}
            label="Choose a PDF receipt"
            onChange={handlePickerChange}
          />

          {!file ? (
            <>
              <section aria-label="Choose receipt source" className="scan-start-card">
                <div className="scan-start-card__illustration">
                  <span><FileText aria-hidden="true" size={45} /></span>
                  <Camera aria-hidden="true" className="scan-start-card__camera" size={28} />
                  <ScanLine aria-hidden="true" className="scan-start-card__scanline" size={76} />
                </div>
                <div className="scan-start-card__copy">
                  <h2>Scan a receipt</h2>
                  <p>Take a photo or choose an existing document.</p>
                </div>
                <button
                  className="primary-button scan-camera-button"
                  onClick={() => cameraInputRef.current?.click()}
                  type="button"
                >
                  <Camera aria-hidden="true" size={20} />
                  Take Photo
                </button>
                <div className="scan-source-options">
                  <button
                    className="scan-source-button"
                    onClick={() => galleryInputRef.current?.click()}
                    type="button"
                  >
                    <ImagePlus aria-hidden="true" size={19} />
                    <span>Choose from Gallery</span>
                  </button>
                  <button
                    className="scan-source-button"
                    onClick={() => pdfInputRef.current?.click()}
                    type="button"
                  >
                    <FileText aria-hidden="true" size={19} />
                    <span>Choose PDF</span>
                  </button>
                </div>
                <p className="scan-file-note">JPG, JPEG, PNG, or PDF · Up to 10 MB</p>
              </section>
              <section className="scan-tips-card" aria-labelledby="scan-tips-title">
                <h3 id="scan-tips-title">For best results</h3>
                <ul>
                  <li>Keep the receipt flat</li>
                  <li>Use good lighting</li>
                  <li>Include the entire receipt</li>
                  <li>Avoid blurry photos</li>
                </ul>
              </section>
            </>
          ) : (
            <section aria-label="Receipt preview" className="scan-preview">
              <div className="scan-preview__heading">
                <h2>Receipt preview</h2>
              </div>
              {isImage && previewUrl ? (
                <div className="scan-preview__image-wrap">
                  <img alt={`Preview of ${file.name}`} src={previewUrl} />
                </div>
              ) : isPdf ? (
                <div className="pdf-preview">
                  <span className="pdf-preview__icon"><FileText aria-hidden="true" size={28} /></span>
                  <div className="pdf-preview__details">
                    <strong title={file.name}>{file.name}</strong>
                    <span>{formatFileSize(file.size)}</span>
                  </div>
                  <span className="pdf-preview__badge">PDF</span>
                </div>
              ) : (
                <div className="pdf-preview">
                  <span className="pdf-preview__icon"><FileText aria-hidden="true" size={28} /></span>
                  <div className="pdf-preview__details">
                    <strong>Unsupported file</strong>
                    <span title={file.name}>{file.name} · {formatFileSize(file.size)}</span>
                  </div>
                </div>
              )}
              {isImage ? (
                <div className="scan-file-row">
                  <span className="scan-file-row__icon">
                    <FileImage aria-hidden="true" size={19} />
                  </span>
                  <span className="scan-file-row__details">
                    <strong title={file.name}>{file.name}</strong>
                    <small>{formatFileSize(file.size)}</small>
                  </span>
                </div>
              ) : null}
              <div className="scan-preview__actions">
                {isImage ? (
                  <button
                    className="scan-preview__action"
                    onClick={() => cameraInputRef.current?.click()}
                    type="button"
                  >
                    <RefreshCw aria-hidden="true" size={16} />
                    Retake
                  </button>
                ) : null}
                <button
                  className="scan-preview__action"
                  onClick={() => (isPdf
                    ? pdfInputRef.current?.click()
                    : galleryInputRef.current?.click())}
                  type="button"
                >
                  Change
                </button>
                <button
                  className="scan-preview__action"
                  onClick={clearFile}
                  type="button"
                >
                  <Trash2 aria-hidden="true" size={16} />
                  Remove
                </button>
              </div>
            </section>
          )}

          {validationError ? (
            <ErrorState
              message={validationError}
              title="This receipt cannot be processed"
            />
          ) : null}
          {error ? (
            <ErrorState
              message={error}
              onRetry={() => void submit()}
              retryLabel="Try Again"
              title="We couldn’t process this receipt"
            />
          ) : null}
          {file && !error ? (
            <div className="scan-sticky-action">
              <button
                className="primary-button scan-submit"
                disabled={Boolean(validationError)}
                onClick={() => void submit()}
                type="button"
              >
                <ArrowUpFromLine aria-hidden="true" size={19} />
                Process Receipt
              </button>
            </div>
          ) : null}
        </>
      )}
    </div>
  )
}
