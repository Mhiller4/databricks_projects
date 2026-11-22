import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import Monitor from './Monitor'
import './index.css'

const Page = location.pathname.startsWith('/monitor') ? Monitor : App
createRoot(document.getElementById('root')!).render(<StrictMode><Page /></StrictMode>)
