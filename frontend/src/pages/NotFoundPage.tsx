import { ArrowLeft, FileQuestion } from 'lucide-react'
import { Link } from 'react-router-dom'

export function NotFoundPage() {
  return (
    <section className="not-found-page">
      <span className="not-found-page__icon">
        <FileQuestion aria-hidden="true" size={30} />
      </span>
      <p className="eyebrow">404 · PAGE NOT FOUND</p>
      <h1>This page isn’t in your workspace</h1>
      <p className="page-description">
        The address may be incorrect, or the page may have moved.
      </p>
      <Link className="button button--primary" to="/">
        <ArrowLeft aria-hidden="true" size={16} />
        Back to home
      </Link>
    </section>
  )
}
