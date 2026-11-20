import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { AppLayout } from './components/layout/AppLayout'
import './App.css'
import { DocumentsPage } from './pages/DocumentsPage'
import { DocumentReviewPage } from './pages/DocumentReviewPage'
import { DashboardPage } from './pages/DashboardPage'
import { NotFoundPage } from './pages/NotFoundPage'
import { UploadPage } from './pages/UploadPage'

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppLayout />}>
          <Route element={<DashboardPage />} path="/" />
          <Route element={<DocumentsPage />} path="/documents" />
          <Route element={<UploadPage />} path="/upload" />
          <Route element={<DocumentReviewPage />} path="/documents/:id" />
          <Route element={<NotFoundPage />} path="*" />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

export default App
