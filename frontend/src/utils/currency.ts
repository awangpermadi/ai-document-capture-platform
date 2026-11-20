export function formatCurrency(
  amount: number | null,
  currency: string | null = 'IDR',
): string {
  if (amount === null) {
    return '—'
  }

  const currencyCode = currency || 'IDR'
  try {
    return new Intl.NumberFormat('id-ID', {
      style: 'currency',
      currency: currencyCode,
      maximumFractionDigits: 0,
    }).format(amount)
  } catch (error) {
    if (!(error instanceof RangeError)) {
      throw error
    }
    return `${currencyCode} ${amount.toLocaleString('id-ID')}`
  }
}
