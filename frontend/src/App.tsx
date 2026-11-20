import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { MobileLayout } from './components/layout/MobileLayout'
import './App.css'
import { DocumentsPage } from './pages/DocumentsPage'
import { DocumentReviewPage } from './pages/DocumentReviewPage'
import { HomePage } from './pages/HomePage'
import { NotFoundPage } from './pages/NotFoundPage'
import { ScanPage } from './pages/ScanPage'

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<MobileLayout />}>
          <Route element={<HomePage />} path="/" />
          <Route element={<DocumentsPage />} path="/documents" />
          <Route element={<ScanPage />} path="/scan" />
          <Route element={<Navigate replace to="/scan" />} path="/upload" />
          <Route element={<DocumentReviewPage />} path="/documents/:id" />
          <Route element={<NotFoundPage />} path="*" />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

export default App
