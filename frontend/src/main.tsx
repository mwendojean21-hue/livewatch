import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { ThemeProvider } from '@/context/ThemeContext'
import { SplashScreen } from '@/components/SplashScreen'
import App from './App.tsx'
import './index.css'

// Filet de sécurité pour le 404 au rafraîchissement (voir public/404.html) :
// si on a été redirigé depuis là, on restaure la vraie route AVANT que
// React Router ne lise window.location, sinon il afficherait "/" au lieu
// de la page demandée.
const redirectPath = sessionStorage.getItem('lw_redirect_path')
if (redirectPath) {
  sessionStorage.removeItem('lw_redirect_path')
  window.history.replaceState(null, '', redirectPath)
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ThemeProvider>
      <SplashScreen />
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </ThemeProvider>
  </StrictMode>,
)
