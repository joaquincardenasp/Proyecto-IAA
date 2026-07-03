import { useEffect, useRef, useState } from 'react'
import { AlertCircle } from 'lucide-react'
import { loginGoogle, type Usuario } from '../api/client'

/* eslint-disable @typescript-eslint/no-explicit-any */

interface Props {
  clientId: string
  onLogin: (user: Usuario) => void
}

export default function LoginScreen({ clientId, onLogin }: Props) {
  const btnRef = useRef<HTMLDivElement>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelado = false
    // Espera a que cargue el script de Google Identity Services.
    const intento = setInterval(() => {
      const google = (window as any).google
      if (!google?.accounts?.id || !btnRef.current) return
      clearInterval(intento)
      google.accounts.id.initialize({
        client_id: clientId,
        callback: async (resp: any) => {
          try {
            const user = await loginGoogle(resp.credential)
            if (!cancelado) onLogin(user)
          } catch (e) {
            if (!cancelado) setError(e instanceof Error ? e.message : 'Error al iniciar sesión')
          }
        },
      })
      google.accounts.id.renderButton(btnRef.current, {
        theme: 'outline', size: 'large', text: 'signin_with', shape: 'pill', locale: 'es',
      })
    }, 200)
    return () => { cancelado = true; clearInterval(intento) }
  }, [onLogin, clientId])

  return (
    <div className="min-h-screen bg-[#F7F8FA] flex items-center justify-center px-4">
      <div className="bg-white border border-gray-200 rounded-2xl shadow-sm p-8 w-full max-w-sm text-center border-t-2 border-t-[#B71C1C]">
        <span className="text-[#B71C1C] font-bold text-lg tracking-widest uppercase">Uandes</span>
        <h1 className="text-base font-semibold text-gray-900 mt-4">Generador de Horarios</h1>
        <p className="text-sm text-gray-500 mt-1 leading-relaxed">
          Facultad de Ingeniería y Ciencias Aplicadas
        </p>

        <div className="mt-8">
          <p className="text-xs text-gray-500 mb-4">
            Inicia sesión con tu correo institucional (<strong>@uandes.cl</strong> o{' '}
            <strong>@miuandes.cl</strong>).
          </p>
          <div ref={btnRef} className="flex justify-center" />
        </div>

        {error && (
          <div className="mt-5 flex items-start gap-2 text-xs text-red-700 bg-red-50 border border-red-200 rounded-lg px-3 py-2 text-left">
            <AlertCircle size={14} className="shrink-0 mt-0.5" />
            <span>{error}</span>
          </div>
        )}
      </div>
    </div>
  )
}
