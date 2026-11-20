import axios from 'axios'

const configuredBaseUrl = import.meta.env.VITE_API_BASE_URL?.trim()

export const apiClient = axios.create({
  baseURL: import.meta.env.DEV ? '/api' : configuredBaseUrl || undefined,
  timeout: 15_000,
  headers: {
    Accept: 'application/json',
  },
})

export class ApiError extends Error {
  readonly status: number | undefined

  constructor(message: string, status?: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export function normalizeApiError(error: unknown): ApiError {
  if (!axios.isAxiosError<unknown>(error)) {
    return new ApiError('Something went wrong. Please try again.')
  }

  const status = error.response?.status

  if (status !== undefined) {
    switch (status) {
      case 400:
        return new ApiError('The document is empty or invalid.', status)
      case 404:
        return new ApiError('The requested document was not found.', status)
      case 409:
        return new ApiError(
          'This document cannot be changed in its current state.',
          status,
        )
      case 413:
        return new ApiError('The selected file is larger than 10 MB.', status)
      case 415:
        return new ApiError(
          'Choose a JPEG, PNG, or PDF file to continue.',
          status,
        )
      case 422:
        return new ApiError(
          'The request or receipt could not be processed.',
          status,
        )
      case 500:
        return new ApiError(
          'The document could not be saved. Please try again.',
          status,
        )
      case 502:
        return new ApiError(
          'The AI document service is unavailable. Please try again.',
          status,
        )
      default:
        if (status >= 500) {
          return new ApiError(
            'The server could not complete the request. Please try again later.',
            status,
          )
        }
        return new ApiError('The request could not be completed.', status)
    }
  }

  if (error.code === 'ECONNABORTED') {
    return new ApiError('The request timed out. Please try again.')
  }

  return new ApiError(
    'Unable to connect to the document service. Check the API configuration and try again.',
  )
}

export function normalizeDocumentDeleteError(error: unknown): ApiError {
  const { status } = normalizeApiError(error)

  switch (status) {
    case 404:
      return new ApiError('The document no longer exists.', status)
    case 409:
      return new ApiError('Approved documents cannot be deleted.', status)
    case 500:
    default:
      return new ApiError('The document could not be deleted. Try again.', status)
  }
}
